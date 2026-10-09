import sqlite3

from fastapi import APIRouter, Depends, Request

from .. import cat, progress
from ..auth import Player, current_player, log_access
from ..db import get_db, transaction
from ..errors import ApiError
from ..presence import hub
from ..ratelimit import limiter

router = APIRouter(prefix="/api/cat")


@router.post("/pet")
def pet(request: Request, me: Player = Depends(current_player), conn: sqlite3.Connection = Depends(get_db)):
    """Pet the inn cat. The first pet of a KST day counts (affection, log row); later ones only purr."""
    if not limiter.allow(f"cat:{me.id}", 30, 60):
        raise ApiError(429, "rate_limited")
    with transaction(conn):
        affection, first, event = cat.pet(conn, me.id)
        log_access(conn, request, "cat", me.id, True)
    # everyone hears the cat (the client plays the meow and, for others, shows who petted it)
    hub.broadcast_threadsafe({"type": "cat", "player": me.id, "affection": affection, "first_today": first})
    if event:
        progress.after_commit(conn, request.app.state.catalog, [event], [])
    return {"affection": affection, "first_today": first}
