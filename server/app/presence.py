"""Online players + WebSocket hub (memory only, one worker).

Every online player is in exactly one presence room: a grid room id, "map" or "dock". Presence messages
(join/leave/move) only go to that room; global ones (room versions, money) go to everyone.

REST handlers run in a threadpool, so they hand messages to the event loop with
run_coroutine_threadsafe via `hub.broadcast_threadsafe`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field

from fastapi import WebSocket

log = logging.getLogger("presence")


@dataclass
class Online:
    id: str
    ws: WebSocket
    x: float
    y: float
    dir: str = "down"
    moving: bool = False
    avatar: dict = field(default_factory=dict)
    room: str = "inn"

    def state(self) -> dict:
        return {"id": self.id, "x": self.x, "y": self.y, "dir": self.dir, "moving": self.moving,
                "avatar": self.avatar, "room": self.room}


class Hub:
    def __init__(self) -> None:
        self.online: dict[str, Online] = {}
        self.loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self) -> None:
        self.loop = asyncio.get_running_loop()

    # -- membership -----------------------------------------------------------

    async def join(self, o: Online) -> None:
        prev = self.online.pop(o.id, None)
        if prev is not None:
            try:
                await prev.ws.close(code=4000, reason="replaced")
            except Exception:
                pass
            await self.broadcast({"type": "leave", "id": o.id}, room=prev.room)
        self.online[o.id] = o
        await self.broadcast({"type": "join", **o.state()}, room=o.room, exclude=o.id)

    async def leave(self, o: Online) -> None:
        if self.online.get(o.id) is o:
            del self.online[o.id]
            await self.broadcast({"type": "leave", "id": o.id}, room=o.room)

    async def move_room(self, o: Online, room: str, x: float, y: float) -> None:
        """Walk through an exit: leave the old presence room, appear in the new one."""
        if o.room == room:
            o.x, o.y, o.moving = x, y, False
            return
        old = o.room
        o.room, o.x, o.y, o.moving = room, x, y, False
        await self.broadcast({"type": "leave", "id": o.id}, room=old)
        await self.broadcast({"type": "join", **o.state()}, room=room, exclude=o.id)

    def snapshot(self, room: str | None = None, exclude: str | None = None) -> list[dict]:
        return [o.state() for pid, o in self.online.items() if pid != exclude and (room is None or o.room == room)]

    def count(self, room: str) -> int:
        return sum(1 for o in self.online.values() if o.room == room)

    # -- messaging -------------------------------------------------------------

    SEND_TIMEOUT = 2.0  # a stalled socket (phone asleep, bad tunnel) must not delay everyone else

    async def broadcast(self, msg: dict, exclude: str | None = None, room: str | None = None) -> None:
        data = json.dumps(msg)
        targets = [o for pid, o in self.online.items() if pid != exclude and (room is None or o.room == room)]
        if not targets:
            return
        results = await asyncio.gather(
            *(asyncio.wait_for(o.ws.send_text(data), self.SEND_TIMEOUT) for o in targets),
            return_exceptions=True,
        )
        for o, r in zip(targets, results):
            if isinstance(r, BaseException):
                await self.leave(o)

    def broadcast_threadsafe(self, msg: dict) -> None:
        if self.loop is None or not self.online:
            return
        asyncio.run_coroutine_threadsafe(self.broadcast(msg), self.loop)

    async def kick(self, player_id: str) -> None:
        o = self.online.get(player_id)
        if o is not None:
            await self.leave(o)
            try:
                await o.ws.close(code=4001, reason="token rotated")
            except Exception:
                pass

    def kick_threadsafe(self, player_id: str) -> None:
        if self.loop is not None and player_id in self.online:
            asyncio.run_coroutine_threadsafe(self.kick(player_id), self.loop)


hub = Hub()
