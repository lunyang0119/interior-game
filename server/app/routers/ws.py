"""WebSocket: presence + live avatar movement.

Protocol (plan §4):
  C→S {"type":"auth","token"}            first message, within 5s
  S→C {"type":"hello","you","room","online":[...],"room_version"}   online = players in your room
  C→S {"type":"enter","room","x","y"}    walk through an exit (room id, "map", "dock", or a mine floor "mine#3"; bare "mine" = floor 1)
  S→C {"type":"entered","room","online","room_version"}            to the sender only (room as normalised, e.g. "mine#1")
  S→C {"type":"error","code":"room_locked","room"}                 enter refused: that place's restoration stage is not done
  S→C {"type":"error","code":"floor_locked","room"}                enter refused: nobody has opened that mine floor yet (mine.can_enter)
  C→S {"type":"move","x","y","dir","moving"}
  S→C {"type":"move","id",...}           to everyone else in the same room
  S→C {"type":"join"|"leave"}            same room only
  S→C {"type":"avatar_look"|"room"|"money"}   everyone
  S→C {"type":"event","event"} | {"type":"progress","rooms","locked"}   everyone (activity log / restoration, progress.py)
  C→S {"type":"ping"} → S→C {"type":"pong"}
"""

import asyncio
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .. import config, progress
from ..auth import lookup_token
from ..db import connect, room_version
from ..presence import Online, hub, split_room
from .me import load_avatar

router = APIRouter()
log = logging.getLogger("ws")

DIRS = {"right", "up", "left", "down"}
MAX_MOVES_PER_SEC = 10
SCENE_EXTENT = 64.0  # map/dock: free coordinates, just keep them sane


def _bounds(app, room: str) -> tuple[float, float]:
    r = app.state.catalog.room_of(room)
    return (float(r.cols), float(r.rows)) if r else (SCENE_EXTENT, SCENE_EXTENT)


def _version(room: str) -> int:
    conn = connect()
    try:
        return room_version(conn, room)
    finally:
        conn.close()


def _is_locked(app, room: str) -> bool:
    conn = connect()
    try:
        return room in progress.locked(conn, app.state.catalog)
    finally:
        conn.close()


def _floor_ok(app, floor: int) -> bool:
    """A mine floor may be entered when it was reached before or the ladder above it is open (then it counts as reached)."""
    from .. import mine
    from ..db import transaction
    m = app.state.mine
    conn = connect()
    try:
        with transaction(conn):
            if not mine.can_enter(conn, m.cfg, floor):
                return False
            mine.open_floor(conn, m.cfg, floor)
            return True
    finally:
        conn.close()


def _mine_floor(app, base: str, floor: int | None) -> int | None:
    """Normalise a mine presence room: the mine without a floor is floor 1; a floor on any other room is refused."""
    m = app.state.mine
    is_mine = m is not None and base == m.cfg.room
    if floor is None:
        return 1 if is_mine else None
    return floor if is_mine and 1 <= floor <= m.cfg.floors else -1


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=5.0)
        msg = json.loads(raw)
        if msg.get("type") != "auth" or not isinstance(msg.get("token"), str):
            await ws.close(code=4401)
            return
    except (asyncio.TimeoutError, WebSocketDisconnect, ValueError):
        try:
            await ws.close(code=4401)
        except Exception:
            pass
        return

    conn = connect()
    try:
        pid = lookup_token(conn, msg["token"])
        if pid is None:
            await ws.close(code=4401)
            return
        avatar = load_avatar(conn, pid)
        cat = ws.app.state.catalog
        base = cat.room
        version = room_version(conn, base.id)
    finally:
        conn.close()

    o = Online(id=pid, ws=ws, x=float(base.spawn["x"]), y=float(base.spawn["y"]), avatar=avatar, room=base.id)
    await ws.send_text(json.dumps({"type": "hello", "you": pid, "room": base.id,
                                   "online": hub.snapshot(room=base.id, exclude=pid), "room_version": version}))
    await hub.join(o)

    window_start = time.monotonic()
    moves_in_window = 0
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            t = msg.get("type")
            if t == "ping":
                await ws.send_text('{"type":"pong"}')
            elif t == "enter":
                room = msg.get("room")
                if not isinstance(room, str):
                    continue
                base, floor = split_room(room)
                if base not in cat.rooms and base not in config.SCENE_ROOMS:
                    continue
                floor = _mine_floor(ws.app, base, floor)
                if floor == -1:
                    continue
                if floor is not None:
                    room = f"{base}#{floor}"
                mx, my = _bounds(ws.app, base)
                try:
                    x = min(max(float(msg.get("x", 0)), 0.0), mx)
                    y = min(max(float(msg.get("y", 0)), 0.0), my)
                except (TypeError, ValueError):
                    continue
                if pid not in config.DEBUG_PLAYERS and await asyncio.to_thread(_is_locked, ws.app, base):
                    await ws.send_text(json.dumps({"type": "error", "code": "room_locked", "room": base}))
                    continue
                if floor is not None and not await asyncio.to_thread(_floor_ok, ws.app, floor):
                    await ws.send_text(json.dumps({"type": "error", "code": "floor_locked", "room": room}))
                    continue
                await hub.move_room(o, room, x, y)
                ver = await asyncio.to_thread(_version, base) if base in cat.rooms else 0
                await ws.send_text(json.dumps({"type": "entered", "room": room,
                                               "online": hub.snapshot(room=room, exclude=pid), "room_version": ver}))
            elif t == "move":
                nowm = time.monotonic()
                if nowm - window_start >= 1.0:
                    window_start, moves_in_window = nowm, 0
                moves_in_window += 1
                if moves_in_window > MAX_MOVES_PER_SEC:
                    continue
                mx, my = _bounds(ws.app, split_room(o.room)[0])
                try:
                    o.x = min(max(float(msg["x"]), 0.0), mx)
                    o.y = min(max(float(msg["y"]), 0.0), my)
                except (KeyError, TypeError, ValueError):
                    continue
                d = msg.get("dir")
                if d in DIRS:
                    o.dir = d
                o.moving = bool(msg.get("moving", False))
                await hub.broadcast({"type": "move", "id": pid, "x": o.x, "y": o.y, "dir": o.dir,
                                     "moving": o.moving}, exclude=pid, room=o.room)
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        log.info("ws %s closed: %s", pid, e)
    finally:
        await hub.leave(o)
