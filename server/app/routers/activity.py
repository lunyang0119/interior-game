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
    return {"events": [_row(r) for r in rows], "max": MAX_EVENTS, "today": today_totals(conn, kst_midnight(now())),
            "progress": progress.all_progress(conn, cat), "locked": sorted(progress.locked(conn, cat))}


def today_totals(conn: sqlite3.Connection, since: int) -> dict:
    """Signed pool changes since `since`, grouped the way the panel shows them.

    Every number is the sum of `events.amount` (+ = the pool grew), so refunds for removed furniture and the
    money a delivery takes back are counted instead of being lost: earned = sheet income, fish = catch value,
    furniture = buys minus refunds (≤ 0 unless more was refunded than bought), sold = junk sales, deliver = the
    reversed catch value (≤ 0).
    """
    sums = {r["kind"]: int(r["s"]) for r in conn.execute(
        "SELECT kind, COALESCE(SUM(amount), 0) AS s FROM events WHERE ts >= ? GROUP BY kind", (since,)).fetchall()}
    fish_count = conn.execute("SELECT COUNT(*) FROM events WHERE kind = 'fish' AND ts >= ?", (since,)).fetchone()[0]
    return {"earned": sums.get("earn", 0), "fish": sums.get("fish", 0), "fish_count": int(fish_count),
            "furniture": sums.get("place", 0) + sums.get("remove", 0), "sold": sums.get("sell", 0),
            "deliver": sums.get("deliver", 0)}
