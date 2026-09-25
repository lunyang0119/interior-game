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

    """Nickname = login. An existing id gets a fresh token (the previous one stops working); a new id is
    recorded on the sheet and created. This is a friends-only room, so knowing the nickname is enough."""
    sheet = request.app.state.sheet
    existing = conn.execute("SELECT 1 FROM players WHERE id = ?", (body.id,)).fetchone() is not None
    info: dict = {}
    if not existing:
        # The sheet is the member list: it records the id in column R (or appends a row for a new nickname).
        try:
            info = sheet.register(conn, body.id)
        except ApiError:
            log_access(conn, request, "register", body.id, False)
            raise

    token = new_token()
    with transaction(conn):
        if existing:
            # keep the row: items.placed_by / ledger.player_id reference it. Only the credential changes.
            conn.execute("UPDATE players SET token_hash = ?, last_seen_ts = ? WHERE id = ?",
                         (hash_token(token), now(), body.id))
            log_access(conn, request, "login", body.id, True)
        else:
            conn.execute(
                "INSERT INTO players(id, token_hash, created_ts, last_seen_ts) VALUES (?, ?, ?, ?)",
                (body.id, hash_token(token), now(), now()),
            )
            conn.execute("INSERT INTO avatars(id) VALUES (?)", (body.id,))
            log_access(conn, request, "register", body.id, True)
    if existing:
        hub.kick_threadsafe(body.id)  # a session on the old token (other device) is disconnected
    return {"id": body.id, "token": token, "existing": existing, "created": bool(info.get("created")),
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
