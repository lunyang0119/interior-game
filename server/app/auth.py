"""Bearer-token auth, access logging, request helpers."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from dataclasses import dataclass

from fastapi import Depends, Request

from . import config
from .db import get_db, now
from .errors import ApiError
from .ratelimit import limiter


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "?"


def ip_hash(request: Request) -> str:
    return hashlib.sha256((config.IP_SALT + client_ip(request)).encode()).hexdigest()[:16]


def short_ua(request: Request) -> str:
    return request.headers.get("user-agent", "")[:80]


def log_access(conn: sqlite3.Connection, request: Request, action: str, player_id: str | None, ok: bool) -> None:
    conn.execute(
        "INSERT INTO access_log(ts, player_id, action, ip_hash, ua, ok) VALUES (?, ?, ?, ?, ?, ?)",
        (now(), player_id, action, ip_hash(request), short_ua(request), int(ok)),
    )


@dataclass
class Player:
    id: str


def bearer_token(request: Request) -> str | None:
    h = request.headers.get("authorization", "")
    if h.lower().startswith("bearer "):
        return h[7:].strip() or None
    return None


def lookup_token(conn: sqlite3.Connection, token: str) -> str | None:
    row = conn.execute("SELECT id FROM players WHERE token_hash = ?", (hash_token(token),)).fetchone()
    return row["id"] if row else None


def current_player(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> Player:
    token = bearer_token(request)
    if not token:
        raise ApiError(401, "unauthorized")
    pid = lookup_token(conn, token)
    if pid is None:
        log_access(conn, request, "auth_fail", None, False)
        raise ApiError(401, "unauthorized")
    limit, per = config.RATE_PLAYER
    if not limiter.allow(f"p:{pid}", limit, per):
        raise ApiError(429, "rate_limited")
    conn.execute("UPDATE players SET last_seen_ts = ? WHERE id = ?", (now(), pid))
    return Player(id=pid)


def optional_player(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> Player | None:
    token = bearer_token(request)
    if not token:
        return None
    pid = lookup_token(conn, token)
    return Player(id=pid) if pid else None
