import sqlite3

from fastapi import APIRouter, Depends, Request

from ..auth import Player, current_player, log_access
from ..db import get_db, transaction
from ..errors import ApiError
from ..presence import hub
from ..schemas import AvatarIn

router = APIRouter(prefix="/api")

AVATAR_FIELDS = ("preset", "skin", "eyes", "hair", "hair_color", "outfit", "acc")


def load_avatar(conn: sqlite3.Connection, player_id: str) -> dict:
    row = conn.execute("SELECT preset, skin, eyes, hair, hair_color, outfit, acc FROM avatars WHERE id = ?", (player_id,)).fetchone()
    return dict(row) if row else {f: 0 for f in AVATAR_FIELDS}


def _money(request: Request, conn: sqlite3.Connection) -> dict:
    sheet = request.app.state.sheet
    return {"balance": sheet.balance(conn), "contributions": sheet.contributions(conn)}


@router.get("/me")
def me(request: Request, me: Player = Depends(current_player), conn: sqlite3.Connection = Depends(get_db)):
    request.app.state.sheet.refresh(conn)
    return {"id": me.id, "avatar": load_avatar(conn, me.id), **_money(request, conn)}


@router.post("/sync")
def sync(request: Request, me: Player = Depends(current_player), conn: sqlite3.Connection = Depends(get_db)):
    refreshed = request.app.state.sheet.manual_sync(conn)
    log_access(conn, request, "sync", me.id, refreshed)
    money = _money(request, conn)
    if refreshed:
        hub.broadcast_threadsafe({"type": "money", "balance": money["balance"]})
    return {"refreshed": refreshed, **money}


@router.put("/avatar")
def put_avatar(body: AvatarIn, request: Request, me: Player = Depends(current_player),
               conn: sqlite3.Connection = Depends(get_db)):
    counts = request.app.state.catalog.layer_counts
    for f in AVATAR_FIELDS:
        v = getattr(body, f)
        n = counts.get(f, 0)
        # layers with no variants must stay 0; others must be inside [0, count)
        if v != 0 and v >= n:
            raise ApiError(400, f"bad_{f}")
    with transaction(conn):
        conn.execute(
            "UPDATE avatars SET preset=?, skin=?, eyes=?, hair=?, hair_color=?, outfit=?, acc=? WHERE id=?",
            (body.preset, body.skin, body.eyes, body.hair, body.hair_color, body.outfit, body.acc, me.id),
        )
    avatar = body.model_dump()
    if me.id in hub.online:
        hub.online[me.id].avatar = avatar
    hub.broadcast_threadsafe({"type": "avatar_look", "id": me.id, "avatar": avatar})
    return {"avatar": avatar}
