"""WebSocket /ws/train: role-filtered push for the train game. Own registry (not presence.hub).

  C→S {"type":"auth","token"}     first message, within 5s (4401 otherwise)
  S→C {"type":"hello","role","state"}
  S→C {"type":"state","state"}    the whole role payload again (lobby/config changes, after a ping to the fugitive …)
  S→C started {line} | round_open {round, deadline_ts, vote_after_ts} | paused | resumed | ended
  S→C submitted {id, submitted, round, order?}   order is omitted for the fugitive; after their ping the fugitive
                                                gets hunter_order {id, submitted, round, order} instead
  S→C fugitive_submitted {submitted, round}     to everyone: whether the fugitive is in, never what
  S→C deadline {deadline_ts, reason: grace | grace_cancel | extend, grace_until?, paused_remaining?}
  S→C vote {target, voters, need, passed, void?}
  S→C bot_thinking {id, round}                  to everyone: an AI hunter ("bot:N") or the AI fugitive ("fugitive") is deciding
  S→C bot_reason {reason}                       fugitive only: the AI's decision + reason
  S→C round_resolved {report, state, log_entry?}   log_entry (and the report's fugitive_path) fugitive only
  S→C captured {by, how, room, line}            the chase ended: status CAPTURED
  S→C escaped {round, line}                     the chase ended at the safety freeze: status ESCAPED (the fugitive won)
  C→S {"type":"ping"} → S→C {"type":"pong"}
Nothing else is accepted from the client: positions change only through round resolution.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError

from ..auth import lookup_token
from ..db import connect

router = APIRouter()
log = logging.getLogger("train.ws")


class ClientMsg(BaseModel):
    type: str


@dataclass
class Conn:
    pid: str
    ws: WebSocket


@dataclass
class TrainHub:
    conns: dict[int, Conn] = field(default_factory=dict)
    SEND_TIMEOUT = 2.0

    def add(self, c: Conn) -> None:
        self.conns[id(c)] = c

    def remove(self, c: Conn) -> None:
        self.conns.pop(id(c), None)

    def pids(self) -> set[str]:
        return {c.pid for c in self.conns.values()}

    async def _send(self, c: Conn, data: str) -> None:
        try:
            await asyncio.wait_for(c.ws.send_text(data), self.SEND_TIMEOUT)
        except Exception:  # noqa: BLE001
            self.remove(c)
            try:
                await c.ws.close(code=4002, reason="stalled")
            except Exception:  # noqa: BLE001
                pass

    async def send_each(self, build: Callable[[str], dict[str, Any] | None]) -> None:
        """build(pid) → message for that player (None = skip). Role filtering happens in `build`."""
        targets = list(self.conns.values())
        await asyncio.gather(*(self._send(c, json.dumps(m, ensure_ascii=False))
                               for c in targets if (m := build(c.pid)) is not None))

    async def broadcast(self, msg: dict[str, Any]) -> None:
        await self.send_each(lambda _pid: msg)


hub = TrainHub()


@router.websocket("/ws/train")
async def ws_train(ws: WebSocket):
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
        except Exception:  # noqa: BLE001
            pass
        return
    conn = connect()
    try:
        pid = lookup_token(conn, msg["token"])
    finally:
        conn.close()
    if pid is None:
        await ws.close(code=4401)
        return

    manager = ws.app.state.train
    c = Conn(pid=pid, ws=ws)
    hub.add(c)
    try:
        role, state = await manager.state_for(pid)
        await ws.send_text(json.dumps({"type": "hello", "role": role, "state": state}, ensure_ascii=False))
        while True:
            raw = await ws.receive_text()
            try:
                m = ClientMsg.model_validate_json(raw)
            except ValidationError:
                continue
            if m.type == "ping":
                await ws.send_text('{"type":"pong"}')
            # every other client message is dropped on purpose
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        log.info("ws/train %s closed: %s", pid, e)
    finally:
        hub.remove(c)
