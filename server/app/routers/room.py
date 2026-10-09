import sqlite3

from fastapi import APIRouter, Depends, Request, Response

from .. import guests, progress
from ..auth import Player, current_player, log_access
from ..catalog import TAG_FIXED, TAG_NOTE, TAG_RUINED, Catalog
from ..db import bump_room_version, get_db, now, room_version, transaction
from ..errors import ApiError
from ..items import find_item, load_items, ruined_count
from ..placement import has_children, price_of, validate_place
from ..presence import hub
from ..schemas import MoveIn, NoteIn, PlaceIn

router = APIRouter(prefix="/api")


def _room_or_404(cat: Catalog, room_id: str):
    room = cat.room_of(room_id)
    if room is None:
        raise ApiError(404, "unknown_room")
    return room


def _notify(room_id: str, version: int, balance: int | None = None, ruined: int | None = None) -> None:
    """A room changed. Everyone gets it (with the pool balance) so HUD/shop/map markers stay in sync."""
    msg: dict = {"type": "room", "room": room_id, "version": version}
    if balance is not None:
        msg["balance"] = balance
    if ruined is not None:
        msg["ruined"] = ruined
    hub.broadcast_threadsafe(msg)


@router.get("/catalog")
def catalog(request: Request, response: Response):
    cat = request.app.state.catalog
    etag = cat.etag()
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-cache"
    return cat.public()


@router.get("/rooms")
def rooms(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    """Every room's version, junk left and restoration progress (map markers, room chips) + the locked places."""
    cat = request.app.state.catalog
    prog = progress.all_progress(conn, cat)
    views = guests.all_views(conn, cat, request.app.state.guests)
    out = []
    for room in cat.rooms.values():
        rows = load_items(conn, room.id)
        out.append({"id": room.id, "name": room.name, "version": room_version(conn, room.id),
                    "ruined": ruined_count(cat, rows), "online": hub.count(room.id), "progress": prog.get(room.id),
                    "comfort": views.get(room.id)})
    return {"rooms": out, "locked": sorted(progress.locked(conn, cat))}


def _room_snapshot(request: Request, response: Response, conn: sqlite3.Connection, room_id: str):
    cat = request.app.state.catalog
    _room_or_404(cat, room_id)
    version = room_version(conn, room_id)
    etag = f'"{version}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-cache"
    rows = load_items(conn, room_id)
    return {"room": room_id, "version": version, "items": [r.__dict__ for r in rows], "ruined": ruined_count(cat, rows)}


@router.get("/room")
def room(request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db)):
    """Alias for the base room (older clients)."""
    return _room_snapshot(request, response, conn, request.app.state.catalog.room.id)


@router.get("/room/{room_id}")
def room_by_id(room_id: str, request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db)):
    return _room_snapshot(request, response, conn, room_id)


@router.post("/room/place")
def place(body: PlaceIn, request: Request, me: Player = Depends(current_player),
          conn: sqlite3.Connection = Depends(get_db)):
    cat: Catalog = request.app.state.catalog
    sheet = request.app.state.sheet
    sheet.refresh(conn)
    events: list[dict] = []
    try:
        with transaction(conn):
            _room_or_404(cat, body.room_id)
            if body.room_id in progress.locked(conn, cat):
                raise ApiError(403, "room_locked")
            it = cat.get(body.item_id)
            if it is None:
                raise ApiError(400, "unknown_item")
            if not it.for_sale:
                raise ApiError(400, "not_for_sale")
            items = load_items(conn, body.room_id)
            p = validate_place(cat, items, body.item_id, body.x, body.y, body.span, room_id=body.room_id)
            price = price_of(it, body.span)
            if sheet.balance(conn) < price:
                raise ApiError(400, "insufficient_funds")
            cur = conn.execute(
                "INSERT INTO items(item_id, x, y, z, parent_uid, placed_by, ts, span, room_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (body.item_id, body.x, body.y, p.z, p.parent_uid, me.id, now(), body.span, body.room_id),
            )
            uid = cur.lastrowid
            conn.execute(
                "INSERT INTO ledger(ts, player_id, amount, kind, item_uid, item_id) VALUES (?, ?, ?, 'place', ?, ?)",
                (now(), me.id, price, uid, body.item_id),
            )
            events.append(progress.add_event(conn, "place", room_id=body.room_id, player_id=me.id, item_id=body.item_id, amount=-price))
            version = bump_room_version(conn, body.room_id)
            completed = progress.advance_rooms(conn, cat, events)
            log_access(conn, request, "place", me.id, True)
    except ApiError:
        log_access(conn, request, "place", me.id, False)
        raise
    balance = sheet.balance(conn)
    _notify(body.room_id, version, balance)
    progress.after_commit(conn, cat, events, completed)
    return {"uid": uid, "balance": balance, "version": version, "room": body.room_id}


@router.post("/room/move")
def move(body: MoveIn, request: Request, me: Player = Depends(current_player),
         conn: sqlite3.Connection = Depends(get_db)):
    cat: Catalog = request.app.state.catalog
    sheet = request.app.state.sheet
    events: list[dict] = []
    try:
        with transaction(conn):
            target = find_item(conn, body.uid)
            if target is None:
                raise ApiError(404, "not_found")
            it = cat.items[target.item_id]
            if it.has_tag(TAG_FIXED):
                raise ApiError(400, "fixed_item")
            if target.room_id in progress.locked(conn, cat):
                raise ApiError(403, "room_locked")
            items = load_items(conn, target.room_id)
            others = [i for i in items if i.uid != body.uid]
            if has_children(body.uid, others):
                raise ApiError(400, "has_children")
            span = body.span if body.span is not None else target.span
            p = validate_place(cat, others, target.item_id, body.x, body.y, span, room_id=target.room_id)
            # wallpaper resized while moving: settle the price difference like a partial place / refund
            diff = price_of(it, span) - price_of(it, target.span)
            if diff > 0 and sheet.balance(conn) < diff:
                raise ApiError(400, "insufficient_funds")
            if diff != 0:
                conn.execute(
                    "INSERT INTO ledger(ts, player_id, amount, kind, item_uid, item_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (now(), me.id, diff, "place" if diff > 0 else "refund", body.uid, target.item_id),
                )
                events.append(progress.add_event(conn, "place" if diff > 0 else "remove", room_id=target.room_id,
                                                 player_id=me.id, item_id=target.item_id, amount=-diff))
            conn.execute("UPDATE items SET x=?, y=?, z=?, parent_uid=?, span=? WHERE uid=?",
                         (body.x, body.y, p.z, p.parent_uid, span, body.uid))
            version = bump_room_version(conn, target.room_id)
            completed = progress.advance_rooms(conn, cat, events)
            log_access(conn, request, "move", me.id, True)
    except ApiError:
        log_access(conn, request, "move", me.id, False)
        raise
    balance = sheet.balance(conn)
    _notify(target.room_id, version, balance)
    progress.after_commit(conn, cat, events, completed)
    return {"uid": body.uid, "version": version, "balance": balance, "room": target.room_id}


@router.delete("/room/item/{uid}")
def remove(uid: int, request: Request, me: Player = Depends(current_player),
           conn: sqlite3.Connection = Depends(get_db)):
    cat: Catalog = request.app.state.catalog
    sheet = request.app.state.sheet
    events: list[dict] = []
    try:
        with transaction(conn):
            target = find_item(conn, uid)
            if target is None:
                raise ApiError(404, "not_found")
            it = cat.items[target.item_id]
            if it.has_tag(TAG_FIXED):
                raise ApiError(400, "fixed_item")
            items = load_items(conn, target.room_id)
            if has_children(uid, items):
                raise ApiError(400, "has_children")
            price = price_of(it, target.span)
            conn.execute("DELETE FROM items WHERE uid = ?", (uid,))
            # seeded junk was never paid for: selling it is how the pool earns from cleaning up
            conn.execute(
                "INSERT INTO ledger(ts, player_id, amount, kind, item_uid, item_id) VALUES (?, ?, ?, 'refund', ?, ?)",
                (now(), me.id, -price, uid, target.item_id),
            )
            events.append(progress.add_event(conn, "sell" if it.has_tag(TAG_RUINED) else "remove", room_id=target.room_id,
                                             player_id=me.id, item_id=target.item_id, amount=price))
            version = bump_room_version(conn, target.room_id)
            ruined = ruined_count(cat, [i for i in items if i.uid != uid])
            completed = progress.advance_rooms(conn, cat, events)
            log_access(conn, request, "remove", me.id, True)
    except ApiError:
        log_access(conn, request, "remove", me.id, False)
        raise
    balance = sheet.balance(conn)
    _notify(target.room_id, version, balance, ruined)
    progress.after_commit(conn, cat, events, completed)
    return {"balance": balance, "version": version, "room": target.room_id, "ruined": ruined}


@router.put("/room/item/{uid}/note")
def write_note(uid: int, body: NoteIn, request: Request, me: Player = Depends(current_player),
               conn: sqlite3.Connection = Depends(get_db)):
    """Write (or clear, with empty text) the text on a `note` item. Shared world: anyone may rewrite any note."""
    cat: Catalog = request.app.state.catalog
    text = body.text.strip()
    try:
        with transaction(conn):
            target = find_item(conn, uid)
            if target is None:
                raise ApiError(404, "not_found")
            if not cat.items[target.item_id].has_tag(TAG_NOTE):
                raise ApiError(400, "not_a_note")
            if text:
                conn.execute("UPDATE items SET note=?, note_by=?, note_ts=? WHERE uid=?", (text, me.id, now(), uid))
            else:
                conn.execute("UPDATE items SET note=NULL, note_by=NULL, note_ts=NULL WHERE uid=?", (uid,))
            version = bump_room_version(conn, target.room_id)
            log_access(conn, request, "note", me.id, True)
    except ApiError:
        log_access(conn, request, "note", me.id, False)
        raise
    _notify(target.room_id, version)
    row = find_item(conn, uid)
    return {"uid": uid, "version": version, "room": target.room_id,
            "note": row.note if row else None, "note_by": row.note_by if row else None, "note_ts": row.note_ts if row else None}
