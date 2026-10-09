"""Guests on the DB side: the daily settlement, reservations and the per-room guest view.

Design: docs/261009_comfort_design.md. The pure maths live in comfort.py; this module runs inside the caller's
transaction like progress.py (settle() → COMMIT → after_settle() broadcasts).

A "guest day" is a KST day that ends at checkout (cfg.checkout_hour_kst): day_key(now) is the ordinal of the
day whose checkout has passed most recently. room_meta 'guest_day:<room>' remembers the last settled day, so
settle() is idempotent and can run on every boot and every minute. Days the server slept through are settled
with the current comfort, at most cfg.max_catchup_days of them.
"""

from __future__ import annotations

import logging
import random
import sqlite3
from datetime import date, datetime, timedelta, timezone

from . import config
from .catalog import Catalog, Room
from .comfort import SET_LAYERS, Comfort, GuestConfig, comfort, nightly_pay, pay_per_guest
from .db import now
from .items import load_items
from .presence import hub
from .progress import _meta, _set_meta, add_event, locked
from .sheet import SheetService

log = logging.getLogger("guests")
KST = timezone(timedelta(hours=9))
LEDGER_KIND = "guest"
RESERVE_ITEM = "item"
RESERVE_DOG = "dog"


def day_key(ts: int, cfg: GuestConfig) -> int:
    """Ordinal of the guest day that ended at the most recent checkout before ts."""
    local = datetime.fromtimestamp(ts, KST) - timedelta(hours=cfg.checkout_hour_kst)
    return local.date().toordinal()


def room_comfort(conn: sqlite3.Connection, cat: Catalog, room: Room, cfg: GuestConfig) -> Comfort:
    return comfort(cat, room, load_items(conn, room.id), cfg.comfort)


def pending_reservation(conn: sqlite3.Connection, room_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM reservations WHERE room_id = ? AND status = 'pending' ORDER BY due_day LIMIT 1",
                        (room_id,)).fetchone()


def _reservation_view(row: sqlite3.Row | None, today: int) -> dict | None:
    if row is None:
        return None
    return {"id": row["id"], "kind": row["kind"], "item_id": row["item_id"], "due_day": row["due_day"],
            "days_left": row["due_day"] - today}


def room_view(conn: sqlite3.Connection, cat: Catalog, room: Room, cfg: GuestConfig, ts: int | None = None) -> dict:
    """What the panel shows for a room: comfort breakdown, tonight's expected guests/pay, the open reservation."""
    today = day_key(ts if ts is not None else now(), cfg)
    c = room_comfort(conn, cat, room, cfg)
    skipped = _meta(conn, f"no_guests_day:{room.id}") == today + 1
    n, pay = (0, 0) if skipped else nightly_pay(c.score, c.beds, cfg.guests)
    return {**c.public(), "guests": n, "per_guest": pay_per_guest(c.score, cfg.guests), "pay": pay, "skipped": skipped,
            "reservation": _reservation_view(pending_reservation(conn, room.id), today)}


def all_views(conn: sqlite3.Connection, cat: Catalog, cfg: GuestConfig) -> dict[str, dict]:
    locks = locked(conn, cat)
    return {r.id: room_view(conn, cat, r, cfg) for r in cat.rooms.values() if r.id not in locks}


def _has_item(cat: Catalog, items, item_id: str | None = None, tag: str | None = None) -> bool:
    for row in items:
        if row.placed_by == config.SEED_PLAYER:
            continue
        it = cat.items[row.item_id]
        if it.has_tag("ruined"):
            continue
        if (item_id is not None and it.id == item_id) or (tag is not None and it.has_tag(tag)):
            return True
    return False


def pick_reservation_item(cat: Catalog, room_items, dominant_set: str | None, cfg: GuestConfig, rng: random.Random) -> str | None:
    """An item the guest asks for: purchasable furniture/surface item, not cheap, not already in the room.

    cfg.reservation.dominant_set_pct of the time it comes from the room's dominant set (nudging toward the set
    bonus), otherwise from the whole shop.
    """
    present = {row.item_id for row in room_items}
    pool = [it for it in cat.items.values()
            if it.for_sale and it.layer in SET_LAYERS and it.price >= cfg.reservation.min_price and it.id not in present]
    if not pool:
        return None
    if dominant_set and rng.randrange(100) < cfg.reservation.dominant_set_pct:
        in_set = [it for it in pool if it.set == dominant_set]
        if in_set:
            pool = in_set
    return rng.choice(pool).id


def _dominant_set(cat: Catalog, items) -> str | None:
    sums: dict[str, int] = {}
    for row in items:
        it = cat.items[row.item_id]
        if row.placed_by != config.SEED_PLAYER and it.set and it.layer in SET_LAYERS:
            sums[it.set] = sums.get(it.set, 0) + it.price
    return max(sums, key=sums.get) if sums else None


def _dog_due(year: int, month: int, rng_seed: int) -> int:
    """The dog lover's day this month: fixed per month (4th..28th) so every boot agrees."""
    return date(year, month, random.Random(f"dog-{year}-{month}-{rng_seed}").randint(4, 28)).toordinal()


def settle(conn: sqlite3.Connection, cat: Catalog, cfg: GuestConfig, ts: int | None = None,
           rng: random.Random | None = None, events: list[dict] | None = None) -> int:
    """Settle every guest day up to day_key(ts) for every open room. Returns the money that entered the pool.

    Inside the caller's transaction. New rooms (or the first boot) start counting from today, so nothing is
    paid retroactively for days before guests existed.
    """
    ts = ts if ts is not None else now()
    rng = rng or random.Random()
    today = day_key(ts, cfg)
    total = 0
    locks = locked(conn, cat)
    open_rooms = [r for r in cat.rooms.values() if r.id not in locks]
    for room in open_rooms:
        last = _meta(conn, f"guest_day:{room.id}")
        if last == 0:
            _set_meta(conn, f"guest_day:{room.id}", today)
            continue
        if last >= today:
            continue
        first = max(last + 1, today - cfg.max_catchup_days + 1)
        items = load_items(conn, room.id)
        c = comfort(cat, room, items, cfg.comfort)
        for d in range(first, today + 1):
            total += _settle_day(conn, cat, room, items, c, cfg, d, ts, rng, events)
        _set_meta(conn, f"guest_day:{room.id}", today)
        if d == today:
            _maybe_reserve(conn, cat, room, items, cfg, today, ts, rng, events)
    _maybe_dog(conn, cat, open_rooms, cfg, today, ts, events)
    return total


def _settle_day(conn, cat, room, items, c: Comfort, cfg, d: int, ts: int, rng, events) -> int:
    per_guest = pay_per_guest(c.score, cfg.guests)
    skipped = _meta(conn, f"no_guests_day:{room.id}") == d
    n, pay = (0, 0) if skipped else nightly_pay(c.score, c.beds, cfg.guests)
    data = {"guests": n, "per_guest": per_guest, "score": c.score, "day": d}
    if skipped:
        data["skipped"] = True

    res = conn.execute("SELECT * FROM reservations WHERE room_id = ? AND status = 'pending' AND due_day <= ?",
                       (room.id, d)).fetchall()
    for r in res:
        if r["kind"] == RESERVE_ITEM:
            ok = c.beds > 0 and _has_item(cat, items, item_id=r["item_id"])
            mult = cfg.reservation.pay_mult
        else:
            ok = c.beds > 0 and (_has_item(cat, items, tag=cfg.dog.tag) or c.score >= cfg.dog.comfort_fallback)
            mult = cfg.dog.pay_mult
        if ok:
            extra = round(per_guest * mult)
            pay += extra
            n += 1
            data[r["kind"] if r["kind"] == RESERVE_DOG else "reserved"] = extra
            conn.execute("UPDATE reservations SET status = 'paid', pay = ? WHERE id = ?", (extra, r["id"]))
        elif r["kind"] == RESERVE_ITEM:
            conn.execute("UPDATE reservations SET status = 'missed' WHERE id = ?", (r["id"],))
            _set_meta(conn, f"no_guests_day:{room.id}", d + 1)
            e = add_event(conn, "missed", room_id=room.id, item_id=r["item_id"], data={"day": d})
            if events is not None:
                events.append(e)
        else:
            conn.execute("UPDATE reservations SET status = 'skipped' WHERE id = ?", (r["id"],))

    data["guests"] = n
    if pay > 0:
        conn.execute("INSERT INTO ledger(ts, player_id, amount, kind, item_uid, item_id) VALUES (?, ?, ?, ?, NULL, ?)",
                     (ts, config.SEED_PLAYER, -pay, LEDGER_KIND, f"room:{room.id}"))
    if pay > 0 or skipped:
        e = add_event(conn, "guest", room_id=room.id, amount=pay if pay else None, data=data)
        if events is not None:
            events.append(e)
    return pay


def _maybe_reserve(conn, cat, room, items, cfg, today: int, ts: int, rng, events) -> None:
    c = comfort(cat, room, items, cfg.comfort)
    if c.beds == 0 or pending_reservation(conn, room.id) is not None or rng.random() >= cfg.reservation.chance:
        return
    item_id = pick_reservation_item(cat, items, _dominant_set(cat, items), cfg, rng)
    if item_id is None:
        return
    lo, hi = cfg.reservation.lead_days
    due = today + rng.randint(lo, hi)
    conn.execute("INSERT INTO reservations(room_id, kind, item_id, due_day, created_ts) VALUES (?, 'item', ?, ?, ?)",
                 (room.id, item_id, due, ts))
    e = add_event(conn, "reserve", room_id=room.id, item_id=item_id, data={"due_day": due, "days": due - today})
    if events is not None:
        events.append(e)


def _maybe_dog(conn, cat, open_rooms: list[Room], cfg, today: int, ts: int, events) -> None:
    """Once a month: the dog lover books the comfiest room (created on the first settlement of the month)."""
    if not open_rooms:
        return
    d = date.fromordinal(today)
    month_key = d.year * 100 + d.month
    if _meta(conn, "dog_month") == month_key:
        return
    _set_meta(conn, "dog_month", month_key)
    due = _dog_due(d.year, d.month, 0)
    if due <= today:
        return  # the server first ran after this month's date: skip the month
    best = max(open_rooms, key=lambda r: room_comfort(conn, cat, r, cfg).score)
    conn.execute("INSERT INTO reservations(room_id, kind, item_id, due_day, created_ts) VALUES (?, 'dog', NULL, ?, ?)",
                 (best.id, due, ts))
    e = add_event(conn, "reserve", room_id=best.id, data={"due_day": due, "days": due - today, "dog": True})
    if events is not None:
        events.append(e)


def after_settle(conn: sqlite3.Connection, events: list[dict], paid: int) -> None:
    """After COMMIT: everyone sees the log rows and, if money came in, the new balance."""
    for e in events:
        hub.broadcast_threadsafe({"type": "event", "event": e})
    if paid:
        hub.broadcast_threadsafe({"type": "money", "balance": SheetService.balance(conn)})
