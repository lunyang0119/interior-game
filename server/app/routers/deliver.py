"""Handing a fresh catch / ore in toward a room's restoration stage instead of keeping its money.

Fish (`/api/fish/finish`) and ore (`/api/mine/hit`) both credit the pool right away and return the ledger `seq`;
delivering it within DELIVER_WINDOW_S reverses that money ('deliver' ledger row) and adds a `deliveries` row
the stage's `deliver` need (same `kind`) counts. One delivery per catch.
"""

import sqlite3

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from .. import progress
from ..auth import Player, current_player, log_access
from ..db import get_db, now, transaction
from ..errors import ApiError
from ..presence import hub
from ..restore import DELIVER_KINDS

router = APIRouter(prefix="/api")

# A catch can be handed in (instead of keeping the money) for this long after it was landed / broken.
DELIVER_WINDOW_S = 120


class DeliverIn(BaseModel):
    seq: int  # the 'fish' / 'mine' ledger row returned by /api/fish/finish or /api/mine/hit
    room: str | None = None  # which room's stage to count it for (default: the first one that wants it)


@router.post("/deliver")
def deliver(body: DeliverIn, request: Request, me: Player = Depends(current_player),
            conn: sqlite3.Connection = Depends(get_db)):
    sheet = request.app.state.sheet
    cat = request.app.state.catalog
    events: list[dict] = []
    try:
        with transaction(conn):
            row = conn.execute("SELECT seq, ts, player_id, amount, kind, item_id FROM ledger WHERE seq = ?",
                               (body.seq,)).fetchone()
            if row is None or row["kind"] not in DELIVER_KINDS:
                raise ApiError(404, "not_found")
            kind = str(row["kind"])
            if row["player_id"] != me.id:
                raise ApiError(403, "not_your_catch")
            if now() - int(row["ts"]) > DELIVER_WINDOW_S:
                raise ApiError(400, "deliver_expired")
            if conn.execute("SELECT 1 FROM deliveries WHERE ledger_seq = ?", (body.seq,)).fetchone():
                raise ApiError(400, "already_delivered")
            loot_id = str(row["item_id"]).removeprefix(f"{kind}:")
            wants = progress.open_deliver_needs(conn, cat, kind, loot_id)
            if body.room is not None:
                wants = [w for w in wants if w["room"] == body.room]
            if not wants:
                raise ApiError(400, "nothing_to_deliver")
            target = wants[0]
            value = -int(row["amount"])
            conn.execute(
                "INSERT INTO deliveries(ts, player_id, room_id, stage_idx, kind, item_id, ledger_seq) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (now(), me.id, target["room"], target["stage_idx"], kind, loot_id, body.seq),
            )
            conn.execute(
                "INSERT INTO ledger(ts, player_id, amount, kind, item_uid, item_id) VALUES (?, ?, ?, 'deliver', NULL, ?)",
                (now(), me.id, value, f"{kind}:{loot_id}"),
            )
            events.append(progress.add_event(conn, "deliver", room_id=target["room"], player_id=me.id, item_id=loot_id,
                                             amount=-value, data={"stage": target["stage_idx"], "kind": kind}))
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
