"""Item row queries shared by the room router, restoration progress, seeding and reconcile."""

import sqlite3

from .catalog import TAG_RUINED, Catalog
from .placement import ItemRow

ITEM_COLS = "uid, item_id, x, y, z, parent_uid, placed_by, ts, span, room_id, note, note_by, note_ts"


def load_items(conn: sqlite3.Connection, room_id: str) -> list[ItemRow]:
    rows = conn.execute(f"SELECT {ITEM_COLS} FROM items WHERE room_id = ? ORDER BY uid", (room_id,)).fetchall()
    return [ItemRow(**dict(r)) for r in rows]


def find_item(conn: sqlite3.Connection, uid: int) -> ItemRow | None:
    r = conn.execute(f"SELECT {ITEM_COLS} FROM items WHERE uid = ?", (uid,)).fetchone()
    return ItemRow(**dict(r)) if r else None


def ruined_count(cat: Catalog, rows: list[ItemRow]) -> int:
    return sum(1 for r in rows if cat.items[r.item_id].has_tag(TAG_RUINED))
