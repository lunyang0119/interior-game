import sqlite3

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ..auth import Player, current_player, log_access
from ..db import get_db, now, transaction
from ..errors import ApiError
from ..fishing import HoldSpan
from ..presence import hub
from ..ratelimit import limiter

router = APIRouter(prefix="/api/fish")


class HoldIn(BaseModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)


class FinishIn(BaseModel):
    session: str
    holds: list[HoldIn] = Field(default_factory=list, max_length=64)


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
    s, ok = fishing.finish(me.id, body.session, [HoldSpan(h.start_ms, h.end_ms) for h in body.holds])
    out = {"ok": ok, "id": s.loot.id, "name": s.loot.name, "value": s.loot.value}
    if ok:
        with transaction(conn):
            # money enters the shared pool like a refund; item_id tags it as a catch for the ledger
            conn.execute(
                "INSERT INTO ledger(ts, player_id, amount, kind, item_uid, item_id) VALUES (?, ?, ?, 'fish', NULL, ?)",
                (now(), me.id, -s.loot.value, f"fish:{s.loot.id}"),
            )
            log_access(conn, request, "fish", me.id, True)
        balance = sheet.balance(conn)
        hub.broadcast_threadsafe({"type": "money", "balance": balance})
        hub.broadcast_threadsafe({"type": "fish", "id": me.id, "loot": s.loot.id, "name": s.loot.name, "value": s.loot.value})
        out["balance"] = balance
    else:
        out["balance"] = sheet.balance(conn)
    return out
