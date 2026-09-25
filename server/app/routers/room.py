import sqlite3

from fastapi import APIRouter, Depends, Request, Response

from ..auth import Player, current_player, log_access
from ..db import bump_room_version, get_db, now, room_version, transaction
from ..errors import ApiError
from ..placement import ItemRow, has_children, validate_place
from ..presence import hub
from ..schemas import MoveIn, PlaceIn

router = APIRouter(prefix="/api")


def load_items(conn: sqlite3.Connection) -> list[ItemRow]:
    rows = conn.execute("SELECT uid, item_id, x, y, z, parent_uid, placed_by, ts FROM items ORDER BY uid").fetchall()
    return [ItemRow(**dict(r)) for r in rows]


def _room_changed(conn: sqlite3.Connection) -> int:
    v = bump_room_version(conn)
    return v


def _notify(version: int) -> None:
    hub.broadcast_threadsafe({"type": "room", "version": version})


@router.get("/catalog")
def catalog(request: Request):
    return request.app.state.catalog.public()


@router.get("/room")
def room(request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db)):
    version = room_version(conn)
    etag = f'"{version}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-cache"
    return {"version": version, "items": [r.__dict__ for r in load_items(conn)]}


@router.post("/room/place")
def place(body: PlaceIn, request: Request, me: Player = Depends(current_player),
          conn: sqlite3.Connection = Depends(get_db)):
    cat = request.app.state.catalog
    sheet = request.app.state.sheet
    sheet.refresh(conn)
    try:
        with transaction(conn):
            items = load_items(conn)
            p = validate_place(cat, items, body.item_id, body.x, body.y)
            price = cat.items[body.item_id].price
            if sheet.balance(conn) < price:
                raise ApiError(400, "insufficient_funds")
            cur = conn.execute(
                "INSERT INTO items(item_id, x, y, z, parent_uid, placed_by, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (body.item_id, body.x, body.y, p.z, p.parent_uid, me.id, now()),
            )
            uid = cur.lastrowid
            conn.execute(
                "INSERT INTO ledger(ts, player_id, amount, kind, item_uid, item_id) VALUES (?, ?, ?, 'place', ?, ?)",
                (now(), me.id, price, uid, body.item_id),
            )
            version = _room_changed(conn)
            log_access(conn, request, "place", me.id, True)
    except ApiError:
        log_access(conn, request, "place", me.id, False)
        raise
    _notify(version)
    return {"uid": uid, "balance": sheet.balance(conn), "version": version}


@router.post("/room/move")
def move(body: MoveIn, request: Request, me: Player = Depends(current_player),
         conn: sqlite3.Connection = Depends(get_db)):
    cat = request.app.state.catalog
    try:
        with transaction(conn):
            items = load_items(conn)
            target = next((i for i in items if i.uid == body.uid), None)
            if target is None:
                raise ApiError(404, "not_found")
            others = [i for i in items if i.uid != body.uid]
            if has_children(body.uid, others):
                raise ApiError(400, "has_children")
            p = validate_place(cat, others, target.item_id, body.x, body.y)
            conn.execute("UPDATE items SET x=?, y=?, z=?, parent_uid=? WHERE uid=?",
                         (body.x, body.y, p.z, p.parent_uid, body.uid))
            version = _room_changed(conn)
            log_access(conn, request, "move", me.id, True)
    except ApiError:
        log_access(conn, request, "move", me.id, False)
        raise
    _notify(version)
    return {"uid": body.uid, "version": version}


@router.delete("/room/item/{uid}")
def remove(uid: int, request: Request, me: Player = Depends(current_player),
           conn: sqlite3.Connection = Depends(get_db)):
    cat = request.app.state.catalog
    sheet = request.app.state.sheet
    try:
        with transaction(conn):
            items = load_items(conn)
            target = next((i for i in items if i.uid == uid), None)
            if target is None:
                raise ApiError(404, "not_found")
            if has_children(uid, items):
                raise ApiError(400, "has_children")
            price = cat.items[target.item_id].price
            conn.execute("DELETE FROM items WHERE uid = ?", (uid,))
            conn.execute(
                "INSERT INTO ledger(ts, player_id, amount, kind, item_uid, item_id) VALUES (?, ?, ?, 'refund', ?, ?)",
                (now(), me.id, -price, uid, target.item_id),
            )
            version = _room_changed(conn)
            log_access(conn, request, "remove", me.id, True)
    except ApiError:
        log_access(conn, request, "remove", me.id, False)
        raise
    _notify(version)
    return {"balance": sheet.balance(conn), "version": version}
