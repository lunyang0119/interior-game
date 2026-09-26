"""WebSocket: presence + live avatar movement.

Protocol (plan §4):
  C→S {"type":"auth","token"}            first message, within 5s
  S→C {"type":"hello","you","room","online":[...],"room_version"}   online = players in your room
  C→S {"type":"enter","room","x","y"}    walk through an exit (room id, "map" or "dock")
  S→C {"type":"entered","room","online","room_version"}            to the sender only
  C→S {"type":"move","x","y","dir","moving"}
  S→C {"type":"move","id",...}           to everyone else in the same room
  S→C {"type":"join"|"leave"}            same room only
  S→C {"type":"avatar_look"|"room"|"money"}   everyone
  C→S {"type":"ping"} → S→C {"type":"pong"}
"""

import asyncio
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .. import config
from ..auth import lookup_token
from ..db import connect, room_version
from ..presence import Online, hub
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
                if not isinstance(room, str) or (room not in cat.rooms and room not in config.SCENE_ROOMS):
                    continue
                mx, my = _bounds(ws.app, room)
                try:
                    x = min(max(float(msg.get("x", 0)), 0.0), mx)
                    y = min(max(float(msg.get("y", 0)), 0.0), my)
                except (TypeError, ValueError):
                    continue
                await hub.move_room(o, room, x, y)
                ver = await asyncio.to_thread(_version, room) if room in cat.rooms else 0
                await ws.send_text(json.dumps({"type": "entered", "room": room,
                                               "online": hub.snapshot(room=room, exclude=pid), "room_version": ver}))
            elif t == "move":
                nowm = time.monotonic()
                if nowm - window_start >= 1.0:
                    window_start, moves_in_window = nowm, 0
                moves_in_window += 1
                if moves_in_window > MAX_MOVES_PER_SEC:
                    continue
                mx, my = _bounds(ws.app, o.room)
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
