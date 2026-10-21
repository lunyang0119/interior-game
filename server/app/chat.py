"""Chat: short messages everyone online sees, stored so late joiners can read the last few.

The message comes in over the room game's socket (routers/ws.py, {"type":"chat","text"}), is cleaned and stored
here, and goes back out to *everyone* (not just the sender's presence room) as
{"type":"chat","id","player","room","text","ts"}; the client draws a bubble over the avatar only in `room`.
The train page (/train/) uses its own socket and never sees these.
"""

from __future__ import annotations

import re
import sqlite3

from .db import now

MAX_LEN = 200
HISTORY = 50
RATE_LIMIT = (5, 5.0)  # 5 messages per 5 s per player

_WS = re.compile(r"[ \t\r\f\v]+")
_NL = re.compile(r"\n{3,}")


def clean(text: object) -> str | None:
    """Trim, collapse runs of blanks, cap at MAX_LEN; None when nothing readable is left (or not a string)."""
    if not isinstance(text, str):
        return None
    t = text.replace("\r\n", "\n")
    t = "".join(ch for ch in t if ch == "\n" or ch >= " ")  # drop control characters
    t = _WS.sub(" ", t)
    t = _NL.sub("\n\n", t)
    t = "\n".join(line.strip() for line in t.split("\n")).strip()
    if not t:
        return None
    return t[:MAX_LEN]


def store(conn: sqlite3.Connection, player_id: str, room: str, text: str) -> dict:
    ts = now()
    cur = conn.execute("INSERT INTO chat (ts, player_id, room, text) VALUES (?, ?, ?, ?)", (ts, player_id, room, text))
    return {"id": int(cur.lastrowid), "ts": ts, "player": player_id, "room": room, "text": text}


def recent(conn: sqlite3.Connection, limit: int = HISTORY) -> list[dict]:
    """The newest `limit` messages, oldest first (the order the panel shows them)."""
    rows = conn.execute("SELECT id, ts, player_id, room, text FROM chat ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [{"id": r["id"], "ts": r["ts"], "player": r["player_id"], "room": r["room"], "text": r["text"]}
            for r in reversed(rows)]
