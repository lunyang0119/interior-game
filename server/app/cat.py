"""The inn cat (pure DB helpers, no HTTP).

Every pet counts, from everyone together: the client sends taps in small batches (`cat_taps` rows), and
affection = min(MAX_AFFECTION, total taps // TAPS_PER_LEVEL) — it never decays, so 300 taps make the cat
love the inn forever. comfort.py adds `affection × affection_bonus` to the comfort score of CAT_ROOM only.
Petting is free and never touches the pool; a level-up logs a 'cat' event (the only noise it makes).
"""

from __future__ import annotations

import sqlite3

from .db import now
from .progress import add_event

CAT_ROOM = "inn"
TAPS_PER_LEVEL = 100
MAX_AFFECTION = 3
MAX_TAPS_PER_CALL = 50  # one request may not claim more than this many taps


def affection_of(total_taps: int) -> int:
    return min(MAX_AFFECTION, total_taps // TAPS_PER_LEVEL)


def taps(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COALESCE(SUM(n), 0) FROM cat_taps").fetchone()[0])


def affection(conn: sqlite3.Connection, ts: int | None = None) -> int:
    """0..MAX_AFFECTION. `ts` is accepted for the callers' convenience; affection does not depend on time."""
    return affection_of(taps(conn))


def pet(conn: sqlite3.Connection, player_id: str, n: int = 1, ts: int | None = None) -> tuple[int, int, bool, dict | None]:
    """Record `n` taps inside the caller's transaction. Returns (affection after, total taps after,
    leveled up, the 'cat' event row when the level rose)."""
    n = max(1, min(MAX_TAPS_PER_CALL, int(n)))
    ts = ts if ts is not None else now()
    before = taps(conn)
    conn.execute("INSERT INTO cat_taps(ts, player_id, n) VALUES (?, ?, ?)", (ts, player_id, n))
    total = before + n
    level = affection_of(total)
    leveled = level > affection_of(before)
    event = add_event(conn, "cat", room_id=CAT_ROOM, player_id=player_id, amount=0,
                      data={"affection": level, "taps": total}) if leveled else None
    return level, total, leveled, event
