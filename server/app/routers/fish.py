import sqlite3

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from .. import progress
from ..auth import Player, current_player, log_access
from ..db import get_db, now, transaction
from ..errors import ApiError
from ..fishing import HoldSpan
from ..presence import hub
from ..ratelimit import limiter

router = APIRouter(prefix="/api/fish")

# A catch can be handed in (instead of keeping the money) for this long after it was landed.
DELIVER_WINDOW_S = 120


class HoldIn(BaseModel):
    start_ms: int = Field(ge=0)  # ms since the schedule arrived
    end_ms: int = Field(ge=0)


class FinishIn(BaseModel):
    session: str
    holds: list[HoldIn] = Field(default_factory=list, max_length=64)
    escaped: bool = False  # the client saw the fish run off and ended early


class DeliverIn(BaseModel):
    seq: int  # the 'fish' ledger row returned by /finish
    room: str | None = None  # which room's stage to count it for (default: the first one that wants it)


@router.get("")
def info(request: Request):
    return request.app.state.fishing.cfg.public()


@router.post("/start")
def start(request: Request, me: Player = Depends(current_player)):
    if not limiter.allow(f"fish:{me.id}", 20, 60):
        raise ApiError(429, "rate_limited")
    s = request.app.state.fishing.start(me.id)
    return s.public()


@router.post("/finish")
def finish(body: FinishIn, request: Request, me: Player = Depends(current_player),
           conn: sqlite3.Connection = Depends(get_db)):
    fishing = request.app.state.fishing
    sheet = request.app.state.sheet
    cat = request.app.state.catalog
    s, res = fishing.finish(me.id, body.session, [HoldSpan(h.start_ms, h.end_ms) for h in body.holds], body.escaped)
    ok = res.ok
    out: dict = {"ok": ok, "pulls": res.pulls, "escaped": res.escaped, "id": s.loot.id, "name": s.loot.name,
                 "value": s.loot.value, "seq": None, "deliverable": []}
    if ok:
        events: list[dict] = []
        with transaction(conn):
            # money enters the shared pool like a refund; item_id tags it as a catch for the ledger (duds add no row)
            if s.loot.value > 0:
                cur = conn.execute(
                    "INSERT INTO ledger(ts, player_id, amount, kind, item_uid, item_id) VALUES (?, ?, ?, 'fish', NULL, ?)",
                    (now(), me.id, -s.loot.value, f"fish:{s.loot.id}"),
                )
                out["seq"] = cur.lastrowid
                out["deliverable"] = [{k: d[k] for k in ("room", "name", "have", "want")}
                                      for d in progress.open_deliver_needs(conn, cat, s.loot.id)]
            events.append(progress.add_event(conn, "fish", player_id=me.id, item_id=s.loot.id, amount=s.loot.value))
            completed = progress.advance_rooms(conn, cat, events)
            log_access(conn, request, "fish", me.id, True)
        balance = sheet.balance(conn)
        hub.broadcast_threadsafe({"type": "money", "balance": balance})
        hub.broadcast_threadsafe({"type": "fish", "id": me.id, "loot": s.loot.id, "name": s.loot.name, "value": s.loot.value})
        progress.after_commit(conn, cat, events, completed)
        out["balance"] = balance
    else:
        out["balance"] = sheet.balance(conn)
    return out


@router.post("/deliver")
def deliver(body: DeliverIn, request: Request, me: Player = Depends(current_player),
            conn: sqlite3.Connection = Depends(get_db)):
    """Hand a fresh catch in toward a room's restoration stage instead of keeping its money.

    The catch was already credited by /finish; delivering reverses that ('deliver' ledger row) and records a
    deliveries row for the stage. One delivery per catch, within DELIVER_WINDOW_S of landing it.
    """
    sheet = request.app.state.sheet
    cat = request.app.state.catalog
    events: list[dict] = []
    try:
        with transaction(conn):
            row = conn.execute("SELECT seq, ts, player_id, amount, item_id FROM ledger WHERE seq = ? AND kind = 'fish'",
                               (body.seq,)).fetchone()
            if row is None:
                raise ApiError(404, "not_found")
            if row["player_id"] != me.id:
                raise ApiError(403, "not_your_catch")
            if now() - int(row["ts"]) > DELIVER_WINDOW_S:
                raise ApiError(400, "deliver_expired")
            if conn.execute("SELECT 1 FROM deliveries WHERE ledger_seq = ?", (body.seq,)).fetchone():
                raise ApiError(400, "already_delivered")
            loot_id = str(row["item_id"]).removeprefix("fish:")
            wants = progress.open_deliver_needs(conn, cat, loot_id)
            if body.room is not None:
                wants = [w for w in wants if w["room"] == body.room]
            if not wants:
                raise ApiError(400, "nothing_to_deliver")
            target = wants[0]
            value = -int(row["amount"])
            conn.execute(
                "INSERT INTO deliveries(ts, player_id, room_id, stage_idx, kind, item_id, ledger_seq) VALUES (?, ?, ?, ?, 'fish', ?, ?)",
                (now(), me.id, target["room"], target["stage_idx"], loot_id, body.seq),
            )
            conn.execute(
                "INSERT INTO ledger(ts, player_id, amount, kind, item_uid, item_id) VALUES (?, ?, ?, 'deliver', NULL, ?)",
                (now(), me.id, value, f"fish:{loot_id}"),
            )
            events.append(progress.add_event(conn, "deliver", room_id=target["room"], player_id=me.id, item_id=loot_id,
                                             amount=-value, data={"stage": target["stage_idx"]}))
            completed = progress.advance_rooms(conn, cat, events)
            have = target["have"] + 1
            log_access(conn, request, "deliver", me.id, True)
    except ApiError:
        log_access(conn, request, "deliver", me.id, False)
        raise
    balance = sheet.balance(conn)
    hub.broadcast_threadsafe({"type": "money", "balance": balance})
    progress.after_commit(conn, cat, events, completed)
    return {"balance": balance, "room": target["room"], "have": min(have, target["want"]), "want": target["want"],
            "completed": [{"room": r, "stage": st.id, "name": st.name} for r, _, st in completed]}
