"""Pre-placed items from data/rooms/<id>.json "seed".

Each room is seeded once (room_meta 'seeded:<id>'), the first time the server sees it. Rows belong to
config.SEED_PLAYER and there is NO ledger entry: selling a ruined seed item is a plain refund, which is how
money enters the shared pool from cleaning up. To seed a room again, delete its 'seeded:<id>' row.
"""

import logging
import sqlite3

from . import config
from .catalog import Catalog, Room
from .db import bump_room_version, now
from .errors import ApiError
from .placement import ItemRow, validate_place

log = logging.getLogger("seed")


def _seeded(conn: sqlite3.Connection, room_id: str) -> bool:
    return conn.execute("SELECT 1 FROM room_meta WHERE k = ?", (f"seeded:{room_id}",)).fetchone() is not None


def seed_room(conn: sqlite3.Connection, catalog: Catalog, room: Room) -> int:
    """Returns the number of rows inserted. Must run inside a transaction, after reconcile."""
    if _seeded(conn, room.id):
        return 0
    rows = conn.execute(
        "SELECT uid, item_id, x, y, z, parent_uid, placed_by, ts, span, room_id FROM items WHERE room_id = ? ORDER BY uid",
        (room.id,),
    ).fetchall()
    present = [ItemRow(**dict(r)) for r in rows]
    inserted = 0
    # parents first (tables before cups), otherwise a seeded cup has nothing to sit on
    order = sorted(room.seed, key=lambda s: catalog.items[s.item_id].layer == "surface_item")
    for sd in order:
        try:
            p = validate_place(catalog, present, sd.item_id, sd.x, sd.y, sd.span, room_id=room.id, relaxed=True)
        except ApiError as e:
            log.warning("seed %s: skipped %s at (%s,%s): %s", room.id, sd.item_id, sd.x, sd.y, e.code)
            continue
        cur = conn.execute(
            "INSERT INTO items(item_id, x, y, z, parent_uid, placed_by, ts, span, room_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sd.item_id, sd.x, sd.y, p.z, p.parent_uid, config.SEED_PLAYER, now(), sd.span, room.id),
        )
        present.append(ItemRow(uid=cur.lastrowid or 0, item_id=sd.item_id, x=sd.x, y=sd.y, z=p.z, parent_uid=p.parent_uid,
                               placed_by=config.SEED_PLAYER, ts=0, span=sd.span, room_id=room.id))
        inserted += 1
    conn.execute("INSERT INTO room_meta(k, v) VALUES (?, 1)", (f"seeded:{room.id}",))
    if inserted:
        bump_room_version(conn, room.id)
    log.info("seeded room %s: %d items", room.id, inserted)
    return inserted
