"""SQLite side of the train game: one JSON snapshot per transition (migration 016) + the admin binding.

`train_games.status` is the manager status: LOBBY | ROUND_OPEN | PAUSED | CAPTURED | ESCAPED | ENDED. Every row that
is not ENDED is the active game on boot (Manager.start restores it; a CAPTURED/ESCAPED game whose webhook line never
went out sends it again).
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..db import connect, now, transaction

ENDED = "ENDED"
ESCAPED = "ESCAPED"   # the fugitive outlasted the chase (safety freeze with escape_on_freeze); restored like CAPTURED


def save_snapshot(row_id: int | None, status: str, snapshot: dict[str, Any]) -> int:
    """Insert (row_id None) or update the game's row; returns the row id. Own connection: called via to_thread."""
    conn = connect()
    try:
        data = json.dumps(snapshot, ensure_ascii=False)
        t = now()
        with transaction(conn):
            if row_id is None:
                cur = conn.execute("INSERT INTO train_games(status, state_json, created_at, updated_at) VALUES (?, ?, ?, ?)",
                                   (status, data, t, t))
                return int(cur.lastrowid)
            conn.execute("UPDATE train_games SET status = ?, state_json = ?, updated_at = ? WHERE id = ?",
                         (status, data, t, row_id))
            return row_id
    finally:
        conn.close()


def load_active(conn: sqlite3.Connection) -> tuple[int, str, dict[str, Any]] | None:
    row = conn.execute("SELECT id, status, state_json FROM train_games WHERE status != ? ORDER BY id DESC LIMIT 1",
                       (ENDED,)).fetchone()
    if row is None:
        return None
    return int(row["id"]), str(row["status"]), json.loads(row["state_json"])


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT v FROM train_meta WHERE k = ?", (key,)).fetchone()
    return str(row["v"]) if row else None


def set_meta(key: str, value: str) -> None:
    conn = connect()
    try:
        with transaction(conn):
            conn.execute("INSERT INTO train_meta(k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v", (key, value))
    finally:
        conn.close()


def load_admin() -> str | None:
    conn = connect()
    try:
        return get_meta(conn, "admin_id")
    finally:
        conn.close()


def load_active_game() -> tuple[int, str, dict[str, Any]] | None:
    conn = connect()
    try:
        return load_active(conn)
    finally:
        conn.close()
