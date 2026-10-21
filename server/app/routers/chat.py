"""GET /api/chat: the newest chat.HISTORY messages, oldest first. Sending goes over the socket (routers/ws.py)."""

import sqlite3

from fastapi import APIRouter, Depends

from .. import chat
from ..auth import Player, current_player
from ..db import get_db

router = APIRouter(prefix="/api")


@router.get("/chat")
def history(_: Player = Depends(current_player), conn: sqlite3.Connection = Depends(get_db)):
    return {"messages": chat.recent(conn), "max": chat.HISTORY, "max_len": chat.MAX_LEN}
