"""Pre-placed items from data/rooms/<id>.json "seed".

Rows belong to config.SEED_PLAYER and there is NO ledger entry: selling a ruined seed item is a plain refund,
which is how money enters the shared pool from cleaning up.

When to (re)seed: the seed list's hash is kept in room_meta ('seed_hash:<id>'). Unchanged hash → nothing
happens, so items the players already sold stay sold. Changed hash (the designer edited the room in the
editor) → every SEED_PLAYER row of that room is replaced by the new list; player-placed items stay.
Older DBs that only have the legacy 'seeded:<id>' marker just record the hash on first start (no reset).
"""

import json
import logging
import sqlite3
import zlib

from . import config
from .catalog import Catalog, Room
from .db import bump_room_version, now
from .errors import ApiError
from .placement import ItemRow, price_of, validate_place

log = logging.getLogger("seed")


def seed_hash(room: Room) -> int:
    data = json.dumps([s.model_dump() for s in room.seed], sort_keys=True, separators=(",", ":"))
    return zlib.crc32(data.encode()) & 0x7FFFFFFF


def _meta(conn: sqlite3.Connection, key: str) -> int | None:
    row = conn.execute("SELECT v FROM room_meta WHERE k = ?", (key,)).fetchone()
    return row[0] if row else None


def _set_meta(conn: sqlite3.Connection, key: str, v: int) -> None:
    conn.execute("INSERT INTO room_meta(k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v", (key, v))


def _clear_seed_rows(conn: sqlite3.Connection, catalog: Catalog, room_id: str) -> int:
    """Drop the room's seed rows. Player items sitting on a seeded table go too, refunded like a remove."""
    seeds = conn.execute("SELECT uid FROM items WHERE room_id = ? AND placed_by = ?", (room_id, config.SEED_PLAYER)).fetchall()
    uids = [r["uid"] for r in seeds]
    if not uids:
        return 0
    q = ",".join("?" * len(uids))
    kids = conn.execute(f"SELECT uid, item_id, placed_by, span FROM items WHERE parent_uid IN ({q}) AND placed_by != ?",
                        (*uids, config.SEED_PLAYER)).fetchall()
    for k in kids:
        it = catalog.items.get(k["item_id"])
        conn.execute("DELETE FROM items WHERE uid = ?", (k["uid"],))
        if it is not None:
            conn.execute(
                "INSERT INTO ledger(ts, player_id, amount, kind, item_uid, item_id) VALUES (?, ?, ?, 'refund', ?, ?)",
                (now(), k["placed_by"], -price_of(it, k["span"]), k["uid"], k["item_id"]),
            )
            log.info("seed %s: refunded %s's %s that sat on a seeded surface", room_id, k["placed_by"], k["item_id"])
    # children (seed cups on seed tables) before parents, FK-safe
    conn.execute(f"DELETE FROM items WHERE uid IN ({q}) AND parent_uid IS NOT NULL", uids)
    conn.execute(f"DELETE FROM items WHERE uid IN ({q})", uids)
    return len(uids)


def seed_room(conn: sqlite3.Connection, catalog: Catalog, room: Room) -> int:
    """Returns the number of rows inserted. Must run inside a transaction, after reconcile."""
    h = seed_hash(room)
    key = f"seed_hash:{room.id}"
    prev = _meta(conn, key)
    if prev == h:
        return 0
    if prev is None and _meta(conn, f"seeded:{room.id}") is not None:
        _set_meta(conn, key, h)  # upgraded from the one-shot marker: keep what is there
        return 0
    removed = _clear_seed_rows(conn, catalog, room.id)
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
    _set_meta(conn, key, h)
    _set_meta(conn, f"seeded:{room.id}", 1)
    if inserted or removed:
        bump_room_version(conn, room.id)
    log.info("seeded room %s: %d items (%d old seed rows replaced)", room.id, inserted, removed)
    return inserted
