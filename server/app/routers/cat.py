import sqlite3

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from .. import cat, progress
from ..auth import Player, current_player, log_access
from ..db import get_db, transaction
from ..errors import ApiError
from ..presence import hub
from ..ratelimit import limiter

router = APIRouter(prefix="/api/cat")


class PetBody(BaseModel):
    taps: int = Field(default=1, ge=1)  # clamped to cat.MAX_TAPS_PER_CALL server-side


@router.post("/pet")
def pet(request: Request, body: PetBody | None = None, me: Player = Depends(current_player),
        conn: sqlite3.Connection = Depends(get_db)):
    """Pet the inn cat `taps` times (the client batches quick taps). Every 100 taps from everyone together
    raise its affection by one, up to 3, for good."""
    if not limiter.allow(f"cat:{me.id}", 60, 60):
        raise ApiError(429, "rate_limited")
    n = body.taps if body else 1
    with transaction(conn):
        affection, total, leveled, event = cat.pet(conn, me.id, n)
        log_access(conn, request, "cat", me.id, True)
    # everyone hears the cat; a level-up also lands in the activity log
    hub.broadcast_threadsafe({"type": "cat", "player": me.id, "affection": affection, "taps": total, "leveled": leveled})
    if event:
        progress.after_commit(conn, request.app.state.catalog, [event], [])
    return {"affection": affection, "taps": total, "leveled": leveled}
