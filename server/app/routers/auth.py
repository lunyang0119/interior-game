import sqlite3

from fastapi import APIRouter, Depends, Request

from .. import config
from ..auth import Player, current_player, hash_token, ip_hash, log_access, new_token
from ..db import get_db, now, transaction
from ..errors import ApiError
from ..presence import hub
from ..ratelimit import limiter
from ..schemas import RegisterIn

router = APIRouter(prefix="/api")


@router.post("/register")
def register(body: RegisterIn, request: Request, conn: sqlite3.Connection = Depends(get_db)):
    limit, per = config.RATE_REGISTER_IP
    if not limiter.allow(f"reg:{ip_hash(request)}", limit, per):
        raise ApiError(429, "rate_limited")

    sheet = request.app.state.sheet
    if conn.execute("SELECT 1 FROM players WHERE id = ?", (body.id,)).fetchone():
        log_access(conn, request, "register", body.id, False)
        raise ApiError(409, "already_registered")
    # The sheet is the member list: it records the id in column R (or appends a row for a new nickname).
    try:
        info = sheet.register(conn, body.id)
    except ApiError:
        log_access(conn, request, "register", body.id, False)
        raise

    token = new_token()
    with transaction(conn):
        conn.execute(
            "INSERT INTO players(id, token_hash, created_ts, last_seen_ts) VALUES (?, ?, ?, ?)",
            (body.id, hash_token(token), now(), now()),
        )
        conn.execute("INSERT INTO avatars(id) VALUES (?)", (body.id,))
        log_access(conn, request, "register", body.id, True)
    return {"id": body.id, "token": token, "created": bool(info.get("created")),
            "name": info.get("name", body.id), "earned": info.get("earned", 0)}


@router.post("/token/rotate")
def rotate(request: Request, me: Player = Depends(current_player), conn: sqlite3.Connection = Depends(get_db)):
    token = new_token()
    with transaction(conn):
        conn.execute("UPDATE players SET token_hash = ? WHERE id = ?", (hash_token(token), me.id))
        log_access(conn, request, "rotate", me.id, True)
    hub.kick_threadsafe(me.id)
    return {"id": me.id, "token": token}


@router.get("/me/logins")
def logins(me: Player = Depends(current_player), conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
        "SELECT ts, action, ip_hash, ua, ok FROM access_log WHERE player_id = ? ORDER BY ts DESC, seq DESC LIMIT 50",
        (me.id,),
    ).fetchall()
    return {"logins": [dict(r) for r in rows]}
