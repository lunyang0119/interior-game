import sqlite3

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from .. import mine as mine_mod
from .. import progress
from ..auth import Player, current_player, log_access
from ..db import get_db, now, transaction
from ..errors import ApiError
from ..presence import hub
from ..ratelimit import limiter

router = APIRouter(prefix="/api/mine")


def _mine(request: Request) -> mine_mod.Mine:
    m = request.app.state.mine
    if m is None:
        raise ApiError(404, "no_mine")  # no data/mine.json
    return m


class HitIn(BaseModel):
    seq: int  # the ore node (from /api/mine/nodes or the ws `mine` message)


@router.get("")
def info(request: Request):
    return _mine(request).cfg.public()


@router.get("/nodes")
def nodes(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    """Today's standing nodes (spawning them first if midnight passed since the last tick)."""
    cfg = _mine(request).cfg
    cat = request.app.state.catalog
    with transaction(conn):
        mine_mod.spawn_day(conn, cat, cfg)
        return mine_mod.nodes(conn, cfg)


@router.post("/hit")
def hit(body: HitIn, request: Request, me: Player = Depends(current_player), conn: sqlite3.Connection = Depends(get_db)):
    """One press of 채광 on a node. Needs the avatar next to it (presence position, `reach` cells). The press that
    breaks the node credits the pool like a catch (ledger 'mine') and may be delivered within the deliver window."""
    mine = _mine(request)
    cfg = mine.cfg
    cat = request.app.state.catalog
    sheet = request.app.state.sheet
    if not limiter.allow(f"mine:{me.id}", 120, 60):
        raise ApiError(429, "rate_limited")
    mine.check_cooldown(me.id)
    o = hub.online.get(me.id)
    if o is None or o.room != cfg.room:
        raise ApiError(403, "not_here")
    foot = mine_mod.foot_cell(o.x, o.y)
    events: list[dict] = []
    completed: list = []
    out: dict
    try:
        with transaction(conn):
            mine_mod.spawn_day(conn, cat, cfg)
            ts = now()
            row = conn.execute("SELECT x, y FROM ore_nodes WHERE seq = ?", (body.seq,)).fetchone()
            if row is not None and not mine_mod.in_reach(cfg, foot, (row["x"], row["y"])):
                raise ApiError(403, "not_here")
            h = mine_mod.hit(conn, cfg, me.id, body.seq, ts)
            out = {"seq": h.seq, "hits_left": h.hits_left, "done": h.done, "left": mine_mod.left_today(conn, cfg, ts)}
            if h.done:
                out.update({"id": h.ore.id, "name": h.ore.name, "value": h.ore.value, "ledger_seq": h.ledger_seq,
                            "deliverable": [{k: d[k] for k in ("room", "name", "have", "want")}
                                            for d in progress.open_deliver_needs(conn, cat, "mine", h.ore.id)] if h.ledger_seq else []})
                events.append(progress.add_event(conn, "mine", room_id=cfg.room, player_id=me.id, item_id=h.ore.id, amount=h.ore.value))
                completed = progress.advance_rooms(conn, cat, events)
            log_access(conn, request, "mine", me.id, True)
    except ApiError:
        log_access(conn, request, "mine", me.id, False)
        raise
    balance = sheet.balance(conn)
    out["balance"] = balance
    msg = {"type": "mine", "seq": h.seq, "x": h.x, "y": h.y, "kind": h.kind, "hits_left": h.hits_left, "by": me.id,
           "done": h.done, "left": out["left"]}
    if h.done:
        msg["loot"] = {"id": h.ore.id, "name": h.ore.name, "value": h.ore.value}
        hub.broadcast_threadsafe({"type": "money", "balance": balance})
    hub.broadcast_threadsafe(msg, room=cfg.room)
    progress.after_commit(conn, cat, events, completed)
    return out
