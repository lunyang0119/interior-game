"""REST /api/train/*. Async handlers: the Manager owns the game on the event loop; roles are re-checked per call."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..auth import Player, current_player, ip_hash, log_access
from ..db import connect
from ..errors import ApiError
from ..ratelimit import limiter
from .game import Manager, RuleApiError

router = APIRouter(prefix="/api/train")

ROOM = Field(min_length=1, max_length=8, pattern=r"^[A-Za-z0-9_\-]+$")


class ClaimIn(BaseModel):
    secret: str = Field(min_length=1, max_length=200)


class CreateIn(BaseModel):
    hunter_count: int = Field(ge=2, le=6, default=4)
    map_id: str | None = Field(default=None, max_length=32)
    overrides: dict[str, Any] = Field(default_factory=dict)
    fugitive_ai: bool = False


class HunterOrderIn(BaseModel):
    type: Literal["move", "search", "scan", "stay"]
    target: str | None = Field(default=None, max_length=8)


class FugitiveOrderIn(BaseModel):
    move: str | None = Field(default=None, max_length=8)
    hack: Literal["doorlock", "distract", "blackout", "hide", "overload"] | None = None
    target: str | None = Field(default=None, max_length=17)


class VoteIn(BaseModel):
    target: str = Field(min_length=1, max_length=32)


class ConfigIn(BaseModel):
    set: dict[str, Any] = Field(default_factory=dict)
    map_id: str | None = Field(default=None, max_length=32)
    reset: bool = False   # drop every runtime override first (then `set` applies on top)


class ExtendIn(BaseModel):
    sec: float = Field(gt=0, le=7 * 86400)


def _mgr(request: Request) -> Manager:
    return request.app.state.train


def _rate(me: Player) -> None:
    if not limiter.allow(f"train:{me.id}", 60, 60):
        raise ApiError(429, "rate_limited")


async def _run(coro):
    """RuleApiError carries the engine's own message for the player; everything else is {"error": code}."""
    try:
        return await coro
    except RuleApiError as e:
        return JSONResponse(status_code=400, content={"error": e.code, "message": e.message})


@router.get("/state")
async def state(request: Request, me: Player = Depends(current_player)):
    _, payload = await _mgr(request).state_for(me.id)
    return payload


@router.post("/claim")
async def claim(body: ClaimIn, request: Request, me: Player = Depends(current_player)):
    if not limiter.allow(f"train_claim:{ip_hash(request)}", 5, 60):
        raise ApiError(429, "rate_limited")
    mgr = _mgr(request)
    try:
        role = await mgr.claim(me.id, body.secret)
    except ApiError:
        conn = connect()
        try:
            log_access(conn, request, "train_claim", me.id, False)
        finally:
            conn.close()
        raise
    return {"role": role}


@router.post("/game")
async def create(body: CreateIn, request: Request, me: Player = Depends(current_player)):
    return await _run(_mgr(request).create(me.id, body.hunter_count, body.map_id, body.overrides, body.fugitive_ai))


@router.post("/join")
async def join(request: Request, me: Player = Depends(current_player)):
    return await _mgr(request).join(me.id, True)


@router.post("/leave")
async def leave(request: Request, me: Player = Depends(current_player)):
    return await _mgr(request).join(me.id, False)


class BotsIn(BaseModel):
    target_count: int = Field(ge=2, le=6, default=6)   # clamped to the game's hunter_count


@router.post("/bots")
async def add_bots(body: BotsIn, request: Request, me: Player = Depends(current_player)):
    return await _mgr(request).add_bots(me.id, body.target_count)


class FugitiveAiIn(BaseModel):
    on: bool = True


@router.post("/fugitive-ai")
async def set_fugitive_ai(body: FugitiveAiIn, request: Request, me: Player = Depends(current_player)):
    return await _mgr(request).set_fugitive_ai(me.id, body.on)


class RevealIn(BaseModel):
    on: bool = True


@router.post("/reveal")
async def set_reveal(body: RevealIn, request: Request, me: Player = Depends(current_player)):
    return await _mgr(request).set_reveal(me.id, body.on)


@router.get("/help")
async def help_text(request: Request, me: Player = Depends(current_player)):
    """The bot's TUTORIAL/HELP (strings.py) with the live scan budget filled in; the client reflows Discord bits."""
    from . import settings
    from . import strings as S
    mgr = _mgr(request)
    budget = (mgr.game.config() if mgr.game is not None else settings.build(4)[0]).get("scan_budget", 1)
    return {"tutorial": S.TUTORIAL.format(scan_budget=budget), "help": S.HELP.format(scan_budget=budget),
            "devices": S.DEVICE_KO, "hacks": S.HACK_KO, "hack_devices": S.HACK_DEVICE, "signals": S.SIGNAL_KO}


@router.delete("/bots")
async def remove_bots(request: Request, me: Player = Depends(current_player)):
    return await _mgr(request).remove_bots(me.id)


@router.post("/start")
async def start(request: Request, me: Player = Depends(current_player)):
    return await _run(_mgr(request).start_game(me.id))


@router.post("/order")
async def order(body: HunterOrderIn, request: Request, me: Player = Depends(current_player)):
    _rate(me)
    return await _run(_mgr(request).hunter_order(me.id, body.type, body.target))


@router.delete("/order")
async def cancel_order(request: Request, me: Player = Depends(current_player)):
    _rate(me)
    return await _mgr(request).cancel_hunter_order(me.id)


@router.post("/fugitive/order")
async def fugitive_order(body: FugitiveOrderIn, request: Request, me: Player = Depends(current_player)):
    _rate(me)
    return await _run(_mgr(request).fugitive_order(me.id, body.move, body.hack, body.target))


@router.delete("/fugitive/order")
async def cancel_fugitive_order(request: Request, me: Player = Depends(current_player)):
    return await _mgr(request).cancel_fugitive_order(me.id)


@router.post("/fugitive/ping")
async def ping(request: Request, me: Player = Depends(current_player)):
    _rate(me)
    return await _run(_mgr(request).ping(me.id))


@router.post("/vote")
async def vote(body: VoteIn, request: Request, me: Player = Depends(current_player)):
    _rate(me)
    return await _mgr(request).vote(me.id, body.target)


@router.get("/config")
async def get_config(request: Request, me: Player = Depends(current_player)):
    return await _mgr(request).get_config(me.id)


@router.put("/config")
async def set_config(body: ConfigIn, request: Request, me: Player = Depends(current_player)):
    return await _run(_mgr(request).set_config(me.id, body.set, body.map_id, reset=body.reset))


@router.post("/pause")
async def pause(request: Request, me: Player = Depends(current_player)):
    return await _mgr(request).pause(me.id)


@router.post("/resume")
async def resume(request: Request, me: Player = Depends(current_player)):
    return await _mgr(request).resume(me.id)


@router.post("/extend")
async def extend(body: ExtendIn, request: Request, me: Player = Depends(current_player)):
    return await _mgr(request).extend(me.id, body.sec)


@router.post("/round/end")
async def end_round(request: Request, me: Player = Depends(current_player)):
    return await _mgr(request).end_round(me.id)


@router.post("/game/end")
async def end_game(request: Request, me: Player = Depends(current_player)):
    return await _mgr(request).end_game(me.id)


@router.get("/maps")
async def maps(request: Request, me: Player = Depends(current_player)):
    return {"maps": Manager.maps()}


@router.get("/maps/{map_id}")
async def map_detail(map_id: str, request: Request, me: Player = Depends(current_player)):
    return Manager.map_detail(map_id)
