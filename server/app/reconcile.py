"""Re-validate stored items against the current catalog/rooms on startup.

Rules and room layouts (wall rows, footprints, layers) live in data/ and change with deploys, so a row
that was legal when placed can become illegal (e.g. a chair on a row that is now part of the wall).
Such rows would render on the wall and block that cell forever, so they are removed and refunded to
the player who placed them, exactly like a manual remove. Rows in a room that no longer exists go the
same way. Rows whose derived z/parent_uid changed are updated in place. Idempotent: a clean DB is a no-op.
"""

import logging
import sqlite3

from . import config
from .catalog import Catalog
from .db import bump_room_version, now
from .errors import ApiError
from .placement import ItemRow, price_of, validate_place

log = logging.getLogger("reconcile")


def reconcile_items(conn: sqlite3.Connection, catalog: Catalog) -> int:
    """Returns the number of rows removed or updated. Must run inside a transaction."""
    rows = conn.execute(
        "SELECT uid, item_id, x, y, z, parent_uid, placed_by, ts, span, room_id FROM items "
        "ORDER BY parent_uid IS NOT NULL, uid"  # parents before children so a dropped table drops its cups
    ).fetchall()
    kept: dict[str, list[ItemRow]] = {}
    changed: dict[str, int] = {}
    for r in rows:
        row = ItemRow(**dict(r))
        item = catalog.items.get(row.item_id)
        try:
            if item is None:
                raise ApiError(400, "unknown_item")
            if row.room_id not in catalog.rooms:
                raise ApiError(404, "unknown_room")
            # seeded rows keep the designer's freedom (past the edge / overlapping); see placement.validate_place
            p = validate_place(catalog, kept.setdefault(row.room_id, []), row.item_id, row.x, row.y, row.span,
                               room_id=row.room_id, relaxed=row.placed_by == config.SEED_PLAYER)
        except ApiError as e:
            conn.execute("DELETE FROM items WHERE uid = ?", (row.uid,))
            if item is not None:
                conn.execute(
                    "INSERT INTO ledger(ts, player_id, amount, kind, item_uid, item_id) VALUES (?, ?, ?, 'refund', ?, ?)",
                    (now(), row.placed_by, -price_of(item, row.span), row.uid, row.item_id),
                )
            log.warning("removed item uid=%s %s in %s at (%s,%s): %s (refunded %s)",
                        row.uid, row.item_id, row.room_id, row.x, row.y, e.code, row.placed_by)
            changed[row.room_id] = changed.get(row.room_id, 0) + 1
            continue
        if p.z != row.z or p.parent_uid != row.parent_uid:
            conn.execute("UPDATE items SET z=?, parent_uid=? WHERE uid=?", (p.z, p.parent_uid, row.uid))
            row = ItemRow(**{**row.__dict__, "z": p.z, "parent_uid": p.parent_uid})
            changed[row.room_id] = changed.get(row.room_id, 0) + 1
        kept[row.room_id].append(row)
    for rid, n in changed.items():
        if rid in catalog.rooms:
            bump_room_version(conn, rid)
        log.info("reconciled %d item rows in %s", n, rid)
    return sum(changed.values())
