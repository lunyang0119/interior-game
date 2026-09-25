"""SQLite connection + migrations (tracked with PRAGMA user_version)."""

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from . import config

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def now() -> int:
    return int(time.time())


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or config.DB_PATH), isolation_level=None, timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    for f in files:
        version = int(f.name.split("_", 1)[0])
        if version <= current:
            continue
        # executescript commits any open transaction first, so wrap the script itself
        sql = f.read_text(encoding="utf-8")
        conn.executescript("BEGIN;\n" + sql + f"\nPRAGMA user_version = {version};\nCOMMIT;")
        current = version


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """BEGIN IMMEDIATE so validation + writes happen under one writer lock."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


_local = threading.local()


def get_db() -> Iterator[sqlite3.Connection]:
    """One connection per worker thread, reused across requests (skips connect + PRAGMAs each time).

    Handlers run in Starlette's threadpool, so the pool size bounds the number of open connections.
    A connection that failed mid-transaction is rolled back before the next request sees it.
    """
    conn: sqlite3.Connection | None = getattr(_local, "conn", None)
    if conn is None or getattr(_local, "path", None) != str(config.DB_PATH):
        if conn is not None:
            conn.close()
        conn = connect()
        _local.conn = conn
        _local.path = str(config.DB_PATH)
    try:
        yield conn
    finally:
        if conn.in_transaction:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass


def room_version(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT v FROM room_meta WHERE k = 'version'").fetchone()[0]


def bump_room_version(conn: sqlite3.Connection) -> int:
    conn.execute("UPDATE room_meta SET v = v + 1 WHERE k = 'version'")
    return room_version(conn)
