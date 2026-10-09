"""Guests on the DB side: the daily settlement, reservations and the per-unit guest view.

Design: docs/261009_comfort_design.md. The pure maths live in comfort.py; this module runs inside the caller's
transaction like progress.py (settle() → COMMIT → after_settle() broadcasts).

A guest *unit* is a whole room, or — when the room has `zones` — each zone on its own (a guest room on a
floor). Units are keyed "room" or "room:zone"; an item belongs to the zone that contains its anchor cell
(x, y), items outside every zone (hallways) score nowhere.

A "guest day" is a KST day that ends at checkout (cfg.checkout_hour_kst): day_key(now) is the ordinal of the
day whose checkout has passed most recently. room_meta 'guest_day:<unit>' remembers the last settled day, so
settle() is idempotent and can run on every boot and every minute. Days the server slept through are settled
with the current comfort, at most cfg.max_catchup_days of them.
"""

from __future__ import annotations

import logging
import random
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from . import config
from .cat import CAT_ROOM, affection as cat_affection
from .catalog import Catalog, Room, Zone
from .comfort import SET_LAYERS, Comfort, GuestConfig, comfort, nightly_pay, pay_per_guest
from .db import bump_room_version, now
from .errors import ApiError
from .items import load_items
from .placement import ItemRow, validate_place
from .presence import hub
from .progress import _meta, _set_meta, add_event, locked
from .sheet import SheetService

log = logging.getLogger("guests")
KST = timezone(timedelta(hours=9))
LEDGER_KIND = "guest"
RESERVE_ITEM = "item"
RESERVE_DOG = "dog"
TAG_NOTE = "note"
TAG_GUEST_NOTE = "guest_note"  # optional: the note sprite guests prefer (else the cheapest surface `note` item)
MAX_GUEST_NOTES = 2  # per unit; older ones are taken away with the guest
NOTE_TRIES = 24

# What guests write, by comfort band (10–33 / 34–67 / 68+); 해요체, under NOTE_MAX.
NOTES_LOW = [
    "하룻밤 묵고 가요. 솔직히 좀 썰렁했어요…",
    "잠은 잤는데 방이 허전하네요. 다음엔 더 아늑했으면!",
    "침대는 있는데 그게 다였어요. 뭔가 더 있으면 좋겠어요.",
    "바람이 숭숭… 그래도 비는 피했어요. 고마워요.",
]
NOTES_MID = [
    "편하게 쉬었어요. 소소하게 꾸며진 게 마음에 들어요.",
    "아늑했어요! 창가 쪽이 특히 좋았어요.",
    "잘 잤어요. 다음에 또 들를게요.",
    "방이 깔끔하네요. 조금만 더 채우면 완벽할 듯!",
]
NOTES_HIGH = [
    "이런 방은 처음이에요. 집에 가기 싫었어요!",
    "완벽한 밤이었어요. 친구들한테도 꼭 추천할게요.",
    "꾸민 사람 센스가 대단해요. 구석구석 다 예뻐요.",
    "여기서 한 달 살고 싶어요. 정말 고마워요!",
]
NOTES_RESERVED = ["부탁한 걸 정말 준비해 주셨네요! 약속대로 두 배 냈어요.", "예약하길 잘했어요. 원하던 그대로였어요!"]
NOTES_DOG = ["우리 강아지도 푹 잤어요. 🐶 또 올게요!", "개를 이렇게 반겨 주는 곳은 드물어요. 고마워요 🐶"]


@dataclass(frozen=True)
class Unit:
    room: Room
    zone: Zone | None

    @property
    def key(self) -> str:
        return self.room.id if self.zone is None else f"{self.room.id}:{self.zone.id}"

    @property
    def cells(self) -> int:
        return self.room.cells if self.zone is None else self.zone.cells

    def items(self, rows: list[ItemRow]) -> list[ItemRow]:
        if self.zone is None:
            return rows
        return [r for r in rows if self.zone.contains(r.x, r.y)]

    def public(self) -> dict:
        return {"room": self.room.id, "zone": self.zone.id if self.zone else None, "zone_name": self.zone.name if self.zone else None}


def units_of(room: Room) -> list[Unit]:
    return [Unit(room, z) for z in room.zones] if room.zones else [Unit(room, None)]


def day_key(ts: int, cfg: GuestConfig) -> int:
    """Ordinal of the guest day that ended at the most recent checkout before ts."""
    local = datetime.fromtimestamp(ts, KST) - timedelta(hours=cfg.checkout_hour_kst)
    return local.date().toordinal()


def unit_affection(conn: sqlite3.Connection, unit: Unit, ts: int | None = None) -> int:
    """The inn cat's affection (0..3) for units of the cat's room; every other room gets 0."""
    return cat_affection(conn, ts) if unit.room.id == CAT_ROOM else 0


def unit_comfort(cat: Catalog, unit: Unit, rows: list[ItemRow], cfg: GuestConfig, affection: int = 0) -> Comfort:
    return comfort(cat, unit.cells, unit.items(rows), cfg.comfort, affection)


def pending_reservation(conn: sqlite3.Connection, unit: Unit) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM reservations WHERE room_id = ? AND zone_id IS ? AND status = 'pending' ORDER BY due_day LIMIT 1",
        (unit.room.id, unit.zone.id if unit.zone else None)).fetchone()


def _reservation_view(row: sqlite3.Row | None, today: int, cat: Catalog, items: list[ItemRow], c: Comfort,
                      cfg: GuestConfig) -> dict | None:
    """`ready` = the unit already satisfies the request (the 📋 board shows ✓ / what is still missing)."""
    if row is None:
        return None
    if row["kind"] == RESERVE_DOG:
        ready = c.beds > 0 and (_has_item(cat, items, tag=cfg.dog.tag) or c.score >= cfg.dog.comfort_fallback)
    else:
        ready = c.beds > 0 and _has_item(cat, items, item_id=row["item_id"])
    return {"id": row["id"], "kind": row["kind"], "item_id": row["item_id"], "due_day": row["due_day"],
            "days_left": row["due_day"] - today, "ready": ready}


def unit_view(conn: sqlite3.Connection, cat: Catalog, unit: Unit, rows: list[ItemRow], cfg: GuestConfig,
              ts: int | None = None) -> dict:
    """What the panel shows for a unit: comfort breakdown, tonight's expected guests/pay, the open reservation."""
    today = day_key(ts if ts is not None else now(), cfg)
    c = unit_comfort(cat, unit, rows, cfg, unit_affection(conn, unit, ts))
    skipped = _meta(conn, f"no_guests_day:{unit.key}") == today + 1
    n, pay = (0, 0) if skipped else nightly_pay(c.score, c.beds, cfg.guests)
    return {**unit.public(), **c.public(), "guests": n, "per_guest": pay_per_guest(c.score, cfg.guests), "pay": pay,
            "skipped": skipped,
            "reservation": _reservation_view(pending_reservation(conn, unit), today, cat, unit.items(rows), c, cfg)}


def room_view(conn: sqlite3.Connection, cat: Catalog, room: Room, cfg: GuestConfig, ts: int | None = None) -> dict[str, dict]:
    """{unit key: view} for every unit of a room."""
    rows = load_items(conn, room.id)
    return {u.key: unit_view(conn, cat, u, rows, cfg, ts) for u in units_of(room)}


def all_views(conn: sqlite3.Connection, cat: Catalog, cfg: GuestConfig, ts: int | None = None) -> dict[str, dict]:
    locks = locked(conn, cat)
    out: dict[str, dict] = {}
    for r in cat.rooms.values():
        if r.id not in locks:
            out.update(room_view(conn, cat, r, cfg, ts))
    return out


def _has_item(cat: Catalog, items: list[ItemRow], item_id: str | None = None, tag: str | None = None) -> bool:
    for row in items:
        if row.placed_by == config.SEED_PLAYER:
            continue
        it = cat.items[row.item_id]
        if it.has_tag("ruined"):
            continue
        if (item_id is not None and it.id == item_id) or (tag is not None and it.has_tag(tag)):
            return True
    return False


def pick_reservation_item(cat: Catalog, unit_items: list[ItemRow], dominant_set: str | None, cfg: GuestConfig,
                          rng: random.Random) -> str | None:
    """An item the guest asks for: purchasable furniture/surface item, not cheap, not already in the unit.

    cfg.reservation.dominant_set_pct of the time it comes from the unit's dominant set (nudging toward the set
    bonus), otherwise from the whole shop.
    """
    present = {row.item_id for row in unit_items}
    pool = [it for it in cat.items.values()
            if it.for_sale and it.layer in SET_LAYERS and it.price >= cfg.reservation.min_price and it.id not in present]
    if not pool:
        return None
    if dominant_set and rng.randrange(100) < cfg.reservation.dominant_set_pct:
        in_set = [it for it in pool if it.set == dominant_set]
        if in_set:
            pool = in_set
    return rng.choice(pool).id


def _dominant_set(cat: Catalog, items: list[ItemRow]) -> str | None:
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
           rng: random.Random | None = None, events: list[dict] | None = None,
           rooms_changed: set[str] | None = None) -> int:
    """Settle every guest day up to day_key(ts) for every unit of every open room. Returns the money that
    entered the pool.

    Inside the caller's transaction. New units (or the first boot) start counting from today, so nothing is
    paid retroactively for days before guests existed. Reservations and the dog lover wait until
    cfg.special_after is unlocked. `rooms_changed` collects rooms whose items changed (guest notes); their
    version is bumped here and after_settle() announces them.
    """
    changed: set[str] = set() if rooms_changed is None else rooms_changed
    ts = ts if ts is not None else now()
    rng = rng or random.Random()
    today = day_key(ts, cfg)
    total = 0
    locks = locked(conn, cat)
    special = cfg.special_after is None or cfg.special_after not in locks
    open_units: list[tuple[Unit, list[ItemRow]]] = []
    for room in cat.rooms.values():
        if room.id in locks:
            continue
        rows = load_items(conn, room.id)
        for unit in units_of(room):
            open_units.append((unit, rows))
            last = _meta(conn, f"guest_day:{unit.key}")
            if last == 0:
                _set_meta(conn, f"guest_day:{unit.key}", today)
                continue
            if last >= today:
                continue
            first = max(last + 1, today - cfg.max_catchup_days + 1)
            items = unit.items(rows)
            c = comfort(cat, unit.cells, items, cfg.comfort, unit_affection(conn, unit, ts))
            for d in range(first, today + 1):
                total += _settle_day(conn, cat, unit, items, c, cfg, d, ts, events, rng, changed)
            _set_meta(conn, f"guest_day:{unit.key}", today)
            if special:
                _maybe_reserve(conn, cat, unit, items, c, cfg, today, ts, rng, events)
    if special:
        _maybe_dog(conn, cat, open_units, cfg, today, ts, events)
    for rid in changed:
        bump_room_version(conn, rid)
    return total


def _settle_day(conn, cat, unit: Unit, items: list[ItemRow], c: Comfort, cfg, d: int, ts: int, events,
                rng: random.Random, rooms_changed: set[str] | None = None) -> int:
    per_guest = pay_per_guest(c.score, cfg.guests)
    skipped = _meta(conn, f"no_guests_day:{unit.key}") == d
    n, pay = (0, 0) if skipped else nightly_pay(c.score, c.beds, cfg.guests)
    data = {"guests": n, "per_guest": per_guest, "score": c.score, "day": d, "zone": unit.zone.id if unit.zone else None}
    if skipped:
        data["skipped"] = True

    res = conn.execute(
        "SELECT * FROM reservations WHERE room_id = ? AND zone_id IS ? AND status = 'pending' AND due_day <= ?",
        (unit.room.id, unit.zone.id if unit.zone else None, d)).fetchall()
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
            data["dog" if r["kind"] == RESERVE_DOG else "reserved"] = extra
            conn.execute("UPDATE reservations SET status = 'paid', pay = ? WHERE id = ?", (extra, r["id"]))
        elif r["kind"] == RESERVE_ITEM:
            conn.execute("UPDATE reservations SET status = 'missed' WHERE id = ?", (r["id"],))
            _set_meta(conn, f"no_guests_day:{unit.key}", d + 1)
            e = add_event(conn, "missed", room_id=unit.room.id, item_id=r["item_id"], data={"day": d, "zone": data["zone"]})
            if events is not None:
                events.append(e)
        else:
            conn.execute("UPDATE reservations SET status = 'skipped' WHERE id = ?", (r["id"],))

    data["guests"] = n
    if pay > 0:
        conn.execute("INSERT INTO ledger(ts, player_id, amount, kind, item_uid, item_id) VALUES (?, ?, ?, ?, NULL, ?)",
                     (ts, config.SEED_PLAYER, -pay, LEDGER_KIND, f"room:{unit.key}"))
        if rooms_changed is not None and leave_note(conn, cat, unit, items, c, data, ts, rng):
            rooms_changed.add(unit.room.id)
    if pay > 0 or skipped:
        e = add_event(conn, "guest", room_id=unit.room.id, amount=pay if pay else None, data=data)
        if events is not None:
            events.append(e)
    return pay


def _note_item(cat: Catalog):
    """The sprite a guest writes on: a `guest_note` item if any, else the cheapest surface item tagged `note`."""
    pref = [it for it in cat.items.values() if it.has_tag(TAG_GUEST_NOTE)]
    pool = pref or [it for it in cat.items.values() if it.has_tag(TAG_NOTE) and it.layer == "surface_item"]
    return min(pool, key=lambda it: (it.price, it.id)) if pool else None


def note_text(score: int, data: dict, rng: random.Random) -> str:
    if data.get("dog"):
        return rng.choice(NOTES_DOG)
    if data.get("reserved"):
        return rng.choice(NOTES_RESERVED)
    return rng.choice(NOTES_HIGH if score >= 68 else NOTES_MID if score >= 34 else NOTES_LOW)


def leave_note(conn, cat: Catalog, unit: Unit, items: list[ItemRow], c: Comfort, data: dict, ts: int, rng) -> bool:
    """After a paid night a guest leaves a note on a table in the unit (a random free cell of a surface).

    Needs an `is_surface` furniture inside the unit; otherwise nothing is left. Keeps the newest
    MAX_GUEST_NOTES per unit. Returns True when the room's items changed (the caller bumps/announces it).
    """
    it = _note_item(cat)
    if it is None:
        return False
    surfaces = [r for r in items if cat.items[r.item_id].layer == "furniture" and cat.items[r.item_id].is_surface]
    if not surfaces:
        return False
    room_rows = load_items(conn, unit.room.id)
    cells = []
    for s in surfaces:
        sit = cat.items[s.item_id]
        cells += [(s.x + dx, s.y + dy) for dx in range(sit.w) for dy in range(sit.h)]
    rng.shuffle(cells)
    for x, y in cells[:NOTE_TRIES]:
        try:
            p = validate_place(cat, room_rows, it.id, x, y, room_id=unit.room.id)
        except ApiError:
            continue
        text = note_text(c.score, data, rng)
        by = "개를 좋아하는 손님" if data.get("dog") else "손님"
        conn.execute("INSERT INTO items(item_id, x, y, z, parent_uid, placed_by, ts, span, room_id, note, note_by, note_ts) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)",
                     (it.id, x, y, p.z, p.parent_uid, config.GUEST_PLAYER, ts, unit.room.id, text, by, ts))
        # older notes go with the guest
        old = [r for r in room_rows if r.placed_by == config.GUEST_PLAYER and unit.items([r])]
        old.sort(key=lambda r: (r.ts, r.uid))
        for r in old[: max(0, len(old) + 1 - MAX_GUEST_NOTES)]:
            conn.execute("DELETE FROM items WHERE uid = ?", (r.uid,))
        return True
    return False


def _maybe_reserve(conn, cat, unit: Unit, items: list[ItemRow], c: Comfort, cfg, today: int, ts: int, rng, events) -> None:
    if c.beds == 0 or pending_reservation(conn, unit) is not None or rng.random() >= cfg.reservation.chance:
        return
    item_id = pick_reservation_item(cat, items, _dominant_set(cat, items), cfg, rng)
    if item_id is None:
        return
    lo, hi = cfg.reservation.lead_days
    due = today + rng.randint(lo, hi)
    zone = unit.zone.id if unit.zone else None
    conn.execute("INSERT INTO reservations(room_id, zone_id, kind, item_id, due_day, created_ts) VALUES (?, ?, 'item', ?, ?, ?)",
                 (unit.room.id, zone, item_id, due, ts))
    e = add_event(conn, "reserve", room_id=unit.room.id, item_id=item_id, data={"due_day": due, "days": due - today, "zone": zone})
    if events is not None:
        events.append(e)


def _maybe_dog(conn, cat, open_units: list[tuple[Unit, list[ItemRow]]], cfg, today: int, ts: int, events) -> None:
    """Once a month: the dog lover books the comfiest unit (decided on the first settlement of the month)."""
    if not open_units:
        return
    d = date.fromordinal(today)
    month_key = d.year * 100 + d.month
    if _meta(conn, "dog_month") == month_key:
        return
    _set_meta(conn, "dog_month", month_key)
    due = _dog_due(d.year, d.month, 0)
    if due <= today:
        return  # the server first ran after this month's date: skip the month
    best, _ = max(open_units, key=lambda ur: unit_comfort(cat, ur[0], ur[1], cfg).score)
    zone = best.zone.id if best.zone else None
    conn.execute("INSERT INTO reservations(room_id, zone_id, kind, item_id, due_day, created_ts) VALUES (?, ?, 'dog', NULL, ?, ?)",
                 (best.room.id, zone, due, ts))
    e = add_event(conn, "reserve", room_id=best.room.id, data={"due_day": due, "days": due - today, "dog": True, "zone": zone})
    if events is not None:
        events.append(e)


def after_settle(conn: sqlite3.Connection, events: list[dict], paid: int, rooms_changed: set[str] = frozenset()) -> None:
    """After COMMIT: everyone sees the log rows, rooms with new guest notes refresh, and the balance updates."""
    from .db import room_version

    for e in events:
        hub.broadcast_threadsafe({"type": "event", "event": e})
    for rid in sorted(rooms_changed):
        hub.broadcast_threadsafe({"type": "room", "room": rid, "version": room_version(conn, rid)})
    if paid:
        hub.broadcast_threadsafe({"type": "money", "balance": SheetService.balance(conn)})
