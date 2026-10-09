"""The inn cat (pure DB helpers, no HTTP).

Anyone can pet the cat once a day; the first pet of a KST day stores a `cat_pets` row and logs a 'cat' event.
Affection = how many of the last AFFECTION_DAYS KST days (today included) had a pet, 0..3, and
comfort.py adds `affection × affection_bonus` to the comfort score of CAT_ROOM only. Petting is free and
never touches the pool; the cat just likes being remembered.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from .db import now
from .progress import add_event

KST = timezone(timedelta(hours=9))
AFFECTION_DAYS = 3
CAT_ROOM = "inn"


def day_str(ts: int) -> str:
    return datetime.fromtimestamp(ts, KST).strftime("%Y-%m-%d")


def recent_days(ts: int) -> list[str]:
    """Today and the AFFECTION_DAYS-1 days before it (KST has no DST, so a day is always 86400 s)."""
    return [day_str(ts - i * 86400) for i in range(AFFECTION_DAYS)]


def affection(conn: sqlite3.Connection, ts: int | None = None) -> int:
    days = recent_days(ts if ts is not None else now())
    q = f"SELECT COUNT(*) FROM cat_pets WHERE day IN ({','.join('?' * len(days))})"
    return int(conn.execute(q, days).fetchone()[0])


def pet(conn: sqlite3.Connection, player_id: str, ts: int | None = None) -> tuple[int, bool, dict | None]:
    """Record a pet inside the caller's transaction. Returns (affection after it, first pet today, the
    'cat' event row when one was written)."""
    ts = ts if ts is not None else now()
    cur = conn.execute("INSERT OR IGNORE INTO cat_pets(day, player_id, ts) VALUES (?, ?, ?)", (day_str(ts), player_id, ts))
    first = cur.rowcount == 1
    event = add_event(conn, "cat", room_id=CAT_ROOM, player_id=player_id, amount=0) if first else None
    return affection(conn, ts), first, event
