"""WebSocket: presence + live avatar movement.

Protocol (plan §4):
  C→S {"type":"auth","token"}            first message, within 5s
  S→C {"type":"hello","you","online":[...],"room_version"}
  C→S {"type":"move","x","y","dir","moving"}
  S→C {"type":"move","id",...}           to everyone else
  S→C {"type":"join"|"leave"|"avatar_look"|"room"}
  C→S {"type":"ping"} → S→C {"type":"pong"}
"""

import asyncio
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..auth import lookup_token
from ..db import connect, room_version
from ..presence import Online, hub
from .me import load_avatar

router = APIRouter()
log = logging.getLogger("ws")

DIRS = {"right", "up", "left", "down"}
MAX_MOVES_PER_SEC = 10


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
        version = room_version(conn)
    finally:
        conn.close()

    room = ws.app.state.catalog.room
    o = Online(id=pid, ws=ws, x=float(room.spawn["x"]), y=float(room.spawn["y"]), avatar=avatar)
    await ws.send_text(json.dumps({"type": "hello", "you": pid, "online": hub.snapshot(exclude=pid),
                                   "room_version": version}))
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
            elif t == "move":
                nowm = time.monotonic()
                if nowm - window_start >= 1.0:
                    window_start, moves_in_window = nowm, 0
                moves_in_window += 1
                if moves_in_window > MAX_MOVES_PER_SEC:
                    continue
                try:
                    o.x = min(max(float(msg["x"]), 0.0), float(room.cols))
                    o.y = min(max(float(msg["y"]), 0.0), float(room.rows))
                except (KeyError, TypeError, ValueError):
                    continue
                d = msg.get("dir")
                if d in DIRS:
                    o.dir = d
                o.moving = bool(msg.get("moving", False))
                await hub.broadcast({"type": "move", "id": pid, "x": o.x, "y": o.y, "dir": o.dir,
                                     "moving": o.moving}, exclude=pid)
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        log.info("ws %s closed: %s", pid, e)
    finally:
        await hub.leave(o)
