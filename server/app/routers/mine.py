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
    seq: int  # the ore node (from /api/mine/floor/{n} or the ws `mine` message)


@router.get("")
def info(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    """The mine's rules (ore table, floors) + the deepest floor anyone opened (the entrance offers 1..deepest)."""
    cfg = _mine(request).cfg
    return {**cfg.public(), "deepest": mine_mod.deepest(conn, cfg)}


@router.get("/floor/{floor}")
def floor(floor: int, request: Request, conn: sqlite3.Connection = Depends(get_db)):
    """Today's layout of one floor (generated on first request). 403 floor_locked until someone opened it."""
    cfg = _mine(request).cfg
    cat = request.app.state.catalog
    with transaction(conn):
        if not mine_mod.can_enter(conn, cfg, floor):
            raise ApiError(403, "floor_locked")
        mine_mod.ensure_floor(conn, cat, cfg, floor)
        return mine_mod.floor_view(conn, cfg, floor)


@router.post("/hit")
def hit(body: HitIn, request: Request, me: Player = Depends(current_player), conn: sqlite3.Connection = Depends(get_db)):
    """One press of 채광 on a node. Needs the avatar on that floor next to it (presence position, `reach` cells).
    The press that breaks the node credits the pool like a catch (ledger 'mine') and may be delivered within the
    deliver window; breaking a dud may uncover the ladder down (`ladder`)."""
    mine = _mine(request)
    cfg = mine.cfg
    cat = request.app.state.catalog
    sheet = request.app.state.sheet
    if not limiter.allow(f"mine:{me.id}", 120, 60):
        raise ApiError(429, "rate_limited")
    mine.check_cooldown(me.id)
    o = hub.online.get(me.id)
    if o is None:
        raise ApiError(403, "not_here")
    foot = mine_mod.foot_cell(o.x, o.y)
    events: list[dict] = []
    completed: list = []
    out: dict
    try:
        with transaction(conn):
            ts = now()
            where = mine_mod.node_floor(conn, body.seq)
            if where is not None:
                floor, x, y = where
                if o.room != cfg.presence_room(floor) or not mine_mod.in_reach(cfg, foot, (x, y)):
                    raise ApiError(403, "not_here")
            h = mine_mod.hit(conn, cfg, me.id, body.seq, ts)
            out = {"seq": h.seq, "floor": h.floor, "hits_left": h.hits_left, "done": h.done, "left": mine_mod.left_on(conn, cfg, h.floor, ts)}
            if h.ladder is not None:
                out["ladder"] = {"x": h.ladder[0], "y": h.ladder[1]}
            if h.done:
                out.update({"id": h.ore.id, "name": h.ore.name, "value": h.ore.value, "ledger_seq": h.ledger_seq,
                            "deliverable": [{k: d[k] for k in ("room", "name", "have", "want")}
                                            for d in progress.open_deliver_needs(conn, cat, "mine", h.ore.id)] if h.ledger_seq else []})
                if h.ore.value > 0:
                    events.append(progress.add_event(conn, "mine", room_id=cfg.room, player_id=me.id, item_id=h.ore.id, amount=h.ore.value))
                    completed = progress.advance_rooms(conn, cat, events)
            log_access(conn, request, "mine", me.id, True)
    except ApiError:
        log_access(conn, request, "mine", me.id, False)
        raise
    balance = sheet.balance(conn)
    out["balance"] = balance
    msg = {"type": "mine", "seq": h.seq, "floor": h.floor, "x": h.x, "y": h.y, "kind": h.kind, "hits_left": h.hits_left,
           "by": me.id, "done": h.done, "left": out["left"]}
    if h.ladder is not None:
        msg["ladder"] = out["ladder"]
    if h.done:
        msg["loot"] = {"id": h.ore.id, "name": h.ore.name, "value": h.ore.value}
        if h.ore.value > 0:
            hub.broadcast_threadsafe({"type": "money", "balance": balance})
    hub.broadcast_threadsafe(msg, room=cfg.presence_room(h.floor))
    progress.after_commit(conn, cat, events, completed)
    return out
