"""The activity panel: the last few things that happened, today's totals and every room's restoration progress.

Only the newest MAX_EVENTS rows are ever served: the log is meant as small talk ("who caught what"), not as a
ledger or a leaderboard, so older rows are not reachable from the client at all.
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request

from .. import progress
from ..auth import Player, current_player
from ..db import get_db, now

router = APIRouter(prefix="/api")

MAX_EVENTS = 5
KST = timezone(timedelta(hours=9))


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["data"] = json.loads(d["data"]) if d.get("data") else None
    return d


def kst_midnight(ts: int) -> int:
    """Start of the KST day that contains ts (unix seconds)."""
    local = datetime.fromtimestamp(ts, KST)
    return int(local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())


@router.get("/activity")
def activity(request: Request, me: Player = Depends(current_player), conn: sqlite3.Connection = Depends(get_db)):
    cat = request.app.state.catalog
    rows = conn.execute("SELECT seq, ts, kind, room_id, player_id, item_id, amount, data FROM events ORDER BY seq DESC LIMIT ?",
                        (MAX_EVENTS,)).fetchall()
    since = kst_midnight(now())
    earned = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM events WHERE kind = 'earn' AND ts >= ?", (since,)).fetchone()[0]
    spent = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM ledger WHERE kind = 'place' AND ts >= ?", (since,)).fetchone()[0]
    fish = conn.execute("SELECT COUNT(*) FROM events WHERE kind = 'fish' AND ts >= ?", (since,)).fetchone()[0]
    return {"events": [_row(r) for r in rows], "max": MAX_EVENTS,
            "today": {"earned": int(earned), "spent": int(spent), "fish": int(fish)},
            "progress": progress.all_progress(conn, cat), "locked": sorted(progress.locked(conn, cat))}
