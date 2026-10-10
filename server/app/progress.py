"""Restoration progress on the DB side: evaluate stages, advance them, log events, notify clients.

Everything here runs inside the caller's transaction (handlers call advance_rooms() before COMMIT) except
after_commit(), which broadcasts once the writes are visible.
"""

from __future__ import annotations

import json
import logging
import sqlite3

from .catalog import Catalog, Room
from .db import now
from .items import load_items
from .presence import hub
from .restore import ANY, DELIVER_KINDS, Stage, StageProgress, evaluate, locked_rooms
from .sheet import SheetService

log = logging.getLogger("progress")


def _meta(conn: sqlite3.Connection, key: str) -> int:
    row = conn.execute("SELECT v FROM room_meta WHERE k = ?", (key,)).fetchone()
    return int(row[0]) if row else 0


def _set_meta(conn: sqlite3.Connection, key: str, v: int) -> None:
    conn.execute("INSERT INTO room_meta(k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v", (key, v))


def stages_done(conn: sqlite3.Connection, cat: Catalog) -> dict[str, int]:
    return {r.id: _meta(conn, f"stage:{r.id}") for r in cat.rooms.values() if r.restore}


def deliveries_by_room(conn: sqlite3.Connection, room_id: str, stage_idx: int) -> dict[str, dict[str, int]]:
    """{kind: {loot id: n, ANY: total}} for one room + stage (every DELIVER_KIND is present, maybe empty)."""
    rows = conn.execute("SELECT kind, item_id, COUNT(*) AS n FROM deliveries WHERE room_id = ? AND stage_idx = ? GROUP BY kind, item_id",
                        (room_id, stage_idx)).fetchall()
    out: dict[str, dict[str, int]] = {k: {} for k in DELIVER_KINDS}
    for r in rows:
        out.setdefault(r["kind"], {})[r["item_id"]] = int(r["n"])
    for d in out.values():
        d[ANY] = sum(d.values())
    return out


def current_stage(conn: sqlite3.Connection, cat: Catalog, room: Room, balance: int | None = None) -> StageProgress | None:
    """Progress of the room's first incomplete stage, or None when every stage is done (or none exist)."""
    idx = _meta(conn, f"stage:{room.id}")
    if idx >= len(room.restore):
        return None
    if balance is None:
        balance = SheetService.balance(conn)
    return evaluate(cat, room.restore[idx], idx, load_items(conn, room.id), deliveries_by_room(conn, room.id, idx), balance)


def room_progress(conn: sqlite3.Connection, cat: Catalog, room: Room, balance: int | None = None) -> dict | None:
    """Public shape: {stage, total, done, current: {...} | None}. None for rooms without stages."""
    if not room.restore:
        return None
    done = _meta(conn, f"stage:{room.id}")
    cur = current_stage(conn, cat, room, balance)
    return {"stage": min(done, len(room.restore)), "total": len(room.restore), "done": cur is None,
            "current": cur.public() if cur else None}


def all_progress(conn: sqlite3.Connection, cat: Catalog) -> dict[str, dict]:
    balance = SheetService.balance(conn)
    out: dict[str, dict] = {}
    for r in cat.rooms.values():
        p = room_progress(conn, cat, r, balance)
        if p is not None:
            out[r.id] = p
    return out


def locked(conn: sqlite3.Connection, cat: Catalog) -> set[str]:
    return locked_rooms(cat.rooms, stages_done(conn, cat))


def progress_message(conn: sqlite3.Connection, cat: Catalog) -> dict:
    return {"type": "progress", "rooms": all_progress(conn, cat), "locked": sorted(locked(conn, cat))}


def open_deliver_needs(conn: sqlite3.Connection, cat: Catalog, kind: str, loot_id: str) -> list[dict]:
    """Rooms whose current stage still wants this loot (`kind` = "fish" / "mine"): [{room, name, stage_idx, have, want}]."""
    out = []
    balance = SheetService.balance(conn)
    for room in cat.rooms.values():
        cur = current_stage(conn, cat, room, balance)
        if cur is None:
            continue
        for need, prog in zip(cur.stage.need, cur.needs):
            if need.type == "deliver" and need.kind == kind and not prog.done and (need.id is None or need.id == loot_id):
                out.append({"room": room.id, "name": room.name, "stage_idx": cur.index, "have": prog.have, "want": prog.want})
                break
    return out


def add_event(conn: sqlite3.Connection, kind: str, *, room_id: str | None = None, player_id: str | None = None,
              item_id: str | None = None, amount: int | None = None, data: dict | None = None) -> dict:
    ts = now()
    cur = conn.execute("INSERT INTO events(ts, kind, room_id, player_id, item_id, amount, data) VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (ts, kind, room_id, player_id, item_id, amount, json.dumps(data, ensure_ascii=False) if data else None))
    return {"seq": cur.lastrowid, "ts": ts, "kind": kind, "room_id": room_id, "player_id": player_id,
            "item_id": item_id, "amount": amount, "data": data}


def advance_rooms(conn: sqlite3.Connection, cat: Catalog, events: list[dict] | None = None) -> list[tuple[str, int, Stage]]:
    """Complete every stage whose needs are met (several in a row if so). Returns [(room, index, stage)].

    `events` collects the 'stage' log rows so the caller can broadcast them after COMMIT.
    """
    completed: list[tuple[str, int, Stage]] = []
    for room in cat.rooms.values():
        if not room.restore:
            continue
        while True:
            cur = current_stage(conn, cat, room)
            if cur is None or not cur.done:
                break
            _set_meta(conn, f"stage:{room.id}", cur.index + 1)
            _set_meta(conn, f"stage_ts:{room.id}", now())
            e = add_event(conn, "stage", room_id=room.id, data={"stage": cur.stage.id, "name": cur.stage.name,
                                                                 "index": cur.index, "unlocks": [r.room for r in cur.stage.reward]})
            if events is not None:
                events.append(e)
            completed.append((room.id, cur.index, cur.stage))
            log.info("room %s: stage %d '%s' complete", room.id, cur.index, cur.stage.id)
    return completed


def after_commit(conn: sqlite3.Connection, cat: Catalog, events: list[dict], completed: list) -> None:
    """Push the new log rows to everyone; after a stage completion also the full progress/lock picture."""
    for e in events:
        hub.broadcast_threadsafe({"type": "event", "event": e})
    if completed:
        hub.broadcast_threadsafe(progress_message(conn, cat))
