"""Session manager: one active train game, owned by the event loop.

The engine (engine.py, copied unchanged) is the rule authority. This module adds the server policy around it:
lobby, round timer (the stored deadline is the truth; the sleeping task is only a wake-up), early resolve +
fugitive grace, vote-to-skip, pause/resume/extend, role binding (train_meta.admin_id), snapshots after every
transition (store.py) and role-filtered broadcasts (ws.py). Every mutation runs under one asyncio lock.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable

import httpx

from .. import config as app_config
from ..errors import ApiError
from . import engine as E
from . import settings, store, views
from .strings import CAPTURE_LINE, COMBAT_MODE_ON
from .utils import get_korean_particle
from .ws import hub

log = logging.getLogger("train")

LOBBY, ROUND_OPEN, PAUSED, CAPTURED, ENDED = "LOBBY", E.ROUND_OPEN, E.PAUSED, E.CAPTURED, store.ENDED
TIMER_CHUNK_S = 60.0
MIN_HUNTERS, MAX_HUNTERS = 2, 6


class RuleApiError(ApiError):
    """An engine RuleError: code 'rule' + the engine's own (Korean) message for the player."""

    def __init__(self, message: str, code: str = "rule"):
        super().__init__(400, code)
        self.message = message


# engine RuleError texts that are codes rather than sentences
_RULE_CODES = {"NOT_OPEN": "not_open", "NOT_HUNTER": "not_hunter", "DAZED": "dazed", "UNKNOWN_ROOM": "unknown_room",
               "NOT_ADJACENT": "not_adjacent"}


def _rule(e: E.RuleError) -> RuleApiError:
    msg = str(e)
    return RuleApiError(msg, _RULE_CODES.get(msg, "rule"))


@dataclass
class Policy:
    hunter_count: int = 4
    map_id: str = ""
    overrides: dict[str, Any] = field(default_factory=dict)
    lobby: list[str] = field(default_factory=list)
    round_open_ts: float = 0.0
    deadline_ts: float = 0.0
    grace_until: float | None = None
    paused_remaining: float | None = None
    paused_at: float | None = None
    votes: dict[str, list[str]] = field(default_factory=dict)
    webhook_sent: bool = False


@dataclass
class TrainGame:
    row_id: int | None
    status: str
    policy: Policy
    engine: E.GameState | None = None

    def config(self) -> dict[str, Any]:
        if self.engine is not None:
            return self.engine.config
        return settings.build(self.policy.hunter_count, self.policy.overrides)[0]

    def effective_deadline(self) -> float:
        g = self.policy.grace_until
        return min(self.policy.deadline_ts, g) if g is not None else self.policy.deadline_ts

    def vote_after_ts(self) -> float | None:
        if self.status not in (ROUND_OPEN, PAUSED) or self.engine is None:
            return None
        return self.policy.round_open_ts + float(self.config().get("vote_skip_after_sec", 600))

    def votes_needed(self) -> int:
        n = len(self.engine.hunters) if self.engine is not None else len(self.policy.lobby)
        return (max(n, 1) - 1) // 2 + 1

    def snapshot(self) -> dict[str, Any]:
        return {"engine": self.engine.to_dict() if self.engine is not None else None, "policy": asdict(self.policy)}

    @classmethod
    def from_snapshot(cls, row_id: int, status: str, snap: dict[str, Any]) -> "TrainGame":
        pol = Policy(**snap.get("policy", {}))
        eng = E.GameState.from_dict(snap["engine"]) if snap.get("engine") else None
        return cls(row_id=row_id, status=status, policy=pol, engine=eng)


Webhook = Callable[[str], Awaitable[None]]


async def post_webhook(line: str) -> None:
    url = app_config.TRAIN_WEBHOOK_URL
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(url, json={"content": line})
    except Exception as e:  # noqa: BLE001
        log.warning("train webhook failed: %s", e)


class Manager:
    def __init__(self) -> None:
        self.game: TrainGame | None = None
        self.admin_id: str | None = None
        self.lock = asyncio.Lock()
        self._timer: asyncio.Task | None = None
        self.webhook: Webhook = post_webhook
        self.now: Callable[[], float] = time.time

    # -- lifecycle -------------------------------------------------------------

    async def start(self) -> None:
        self.admin_id = await asyncio.to_thread(store.load_admin)
        row = await asyncio.to_thread(store.load_active_game)
        if row is not None:
            rid, status, snap = row
            try:
                self.game = TrainGame.from_snapshot(rid, status, snap)
            except Exception as e:  # noqa: BLE001
                log.error("train: stored game %d unreadable, ending it: %s", rid, e)
                await asyncio.to_thread(store.save_snapshot, rid, ENDED, snap)
                self.game = None
        g = self.game
        if g is not None and g.status == ROUND_OPEN:
            async with self.lock:
                if g.effective_deadline() <= self.now():
                    log.info("train: round %d expired while the server was down, resolving", g.engine.round_no)
                    await self._resolve(timed_out=True)
                else:
                    self._arm()
        elif g is not None:
            log.info("train: restored game %d (%s)", g.row_id, g.status)

    async def stop(self) -> None:
        self._cancel_timer()

    # -- roles -----------------------------------------------------------------

    def role_of(self, pid: str | None) -> str:
        if pid is not None and pid == self.admin_id:
            return views.FUGITIVE
        g = self.game
        if pid is not None and g is not None:
            if g.engine is not None and pid in g.engine.hunters:
                return views.HUNTER
            if g.engine is None and pid in g.policy.lobby:
                return views.HUNTER
        return views.SPECTATOR

    def _payload(self, pid: str | None) -> dict[str, Any]:
        role = self.role_of(pid)
        if self.game is None:
            return {"status": "IDLE", "role": role, "you": None}
        return views.payload_for(self.game, role, pid)

    async def state_for(self, pid: str | None) -> tuple[str, dict[str, Any]]:
        async with self.lock:
            return self.role_of(pid), self._payload(pid)

    def _require_admin(self, pid: str) -> None:
        if self.admin_id is None or pid != self.admin_id:
            raise ApiError(403, "not_admin")

    def _require_game(self, *statuses: str) -> TrainGame:
        g = self.game
        if g is None:
            raise ApiError(404, "no_game")
        if statuses and g.status not in statuses:
            raise ApiError(409, "paused" if g.status == PAUSED else "not_open")
        return g

    async def claim(self, pid: str, secret: str) -> str:
        import secrets as _s
        real = app_config.TRAIN_ADMIN_SECRET
        if not real:
            raise ApiError(403, "train_disabled")
        if not _s.compare_digest(secret.encode(), real.encode()):
            raise ApiError(403, "bad_secret")
        async with self.lock:
            self.admin_id = pid
            await asyncio.to_thread(store.set_meta, "admin_id", pid)
            g = self.game
            if g is not None and g.engine is None and pid in g.policy.lobby:
                g.policy.lobby.remove(pid)
                await self._save()
        await self._push_state()
        return views.FUGITIVE

    # -- persistence / push -----------------------------------------------------

    async def _save(self) -> None:
        g = self.game
        if g is None:
            return
        g.row_id = await asyncio.to_thread(store.save_snapshot, g.row_id, g.status, g.snapshot())

    async def _push_state(self) -> None:
        await hub.send_each(lambda pid: {"type": "state", "state": self._payload(pid)})

    async def _push(self, msg: dict[str, Any]) -> None:
        await hub.broadcast(msg)

    # -- lobby -----------------------------------------------------------------

    async def create(self, pid: str, hunter_count: int, map_id: str | None, overrides: dict[str, Any] | None) -> dict[str, Any]:
        self._require_admin(pid)
        if not MIN_HUNTERS <= hunter_count <= MAX_HUNTERS:
            raise ApiError(400, "bad_hunter_count")
        async with self.lock:
            g = self.game
            if g is not None and g.status not in (CAPTURED,):
                raise ApiError(409, "game_active")
            if g is not None:
                g.status = ENDED
                await self._save()
                self._cancel_timer()
            ov: dict[str, Any] = {}
            for k, v in (overrides or {}).items():
                try:
                    ov[k] = E.cfgmod.coerce(k, v)
                except E.cfgmod.ConfigError as e:
                    raise RuleApiError(str(e), "bad_config")
            mid = E.cfgmod.normalize_map_id(map_id) if map_id else settings.default_map_id(hunter_count)
            if mid not in E.cfgmod.BUILTIN_MAPS:
                raise ApiError(400, "unknown_map")
            self.game = TrainGame(row_id=None, status=LOBBY, policy=Policy(hunter_count=hunter_count, map_id=mid, overrides=ov))
            await self._save()
            out = self._payload(pid)
        await self._push_state()
        return out

    async def join(self, pid: str, joining: bool) -> dict[str, Any]:
        async with self.lock:
            g = self._require_game(LOBBY)
            if pid == self.admin_id:
                raise ApiError(403, "is_admin")
            if joining:
                if pid not in g.policy.lobby:
                    if len(g.policy.lobby) >= g.policy.hunter_count:
                        raise ApiError(409, "lobby_full")
                    g.policy.lobby.append(pid)
            elif pid in g.policy.lobby:
                g.policy.lobby.remove(pid)
            await self._save()
            out = self._payload(pid)
        await self._push_state()
        return out

    async def start_game(self, pid: str) -> dict[str, Any]:
        self._require_admin(pid)
        async with self.lock:
            g = self._require_game(LOBBY)
            if len(g.policy.lobby) < MIN_HUNTERS:
                raise ApiError(409, "not_enough_hunters")
            cfg, _ = settings.build(g.policy.hunter_count, g.policy.overrides)
            gmap = E.GameMap.builtin(g.policy.map_id)
            try:
                g.engine = E.new_game(gmap, cfg, [(h, h) for h in g.policy.lobby], now=self.now())
            except E.RuleError as e:
                raise _rule(e)
            await self._open_round(g, push=False)
            out = self._payload(pid)
            await self._push({"type": "started", "line": COMBAT_MODE_ON})
            await self._push_state()
            await self._push_round_open(g)
        await self.webhook(COMBAT_MODE_ON)
        return out

    # -- rounds ----------------------------------------------------------------

    async def _open_round(self, g: TrainGame, push: bool = True) -> None:
        """Called under the lock with g.engine.status == ROUND_OPEN (fresh game or after a resolve)."""
        t = self.now()
        g.status = ROUND_OPEN
        g.policy.round_open_ts = t
        g.policy.deadline_ts = t + float(g.engine.config["round_timer_sec"])
        g.policy.grace_until = None
        g.policy.paused_remaining = None
        g.policy.paused_at = None
        g.policy.votes = {}
        await self._save()
        self._arm()
        if push:
            await self._push_round_open(g)

    async def _push_round_open(self, g: TrainGame) -> None:
        await self._push({"type": "round_open", "round": g.engine.round_no, "deadline_ts": g.policy.deadline_ts,
                          "vote_after_ts": g.vote_after_ts()})

    def _cancel_timer(self) -> None:
        t = self._timer
        self._timer = None
        if t is not None and t is not asyncio.current_task() and not t.done():
            t.cancel()

    def _arm(self) -> None:
        self._cancel_timer()
        g = self.game
        if g is not None and g.status == ROUND_OPEN:
            self._timer = asyncio.create_task(self._timer_loop())

    async def _timer_loop(self) -> None:
        """Sleep in chunks and re-read the stored deadline each time: a restart or an extend never leaves a stale
        wake-up in charge. The deadline itself is the truth."""
        while True:
            g = self.game
            if g is None or g.status != ROUND_OPEN:
                return
            rem = g.effective_deadline() - self.now()
            if rem <= 0:
                break
            await asyncio.sleep(min(rem, TIMER_CHUNK_S))
        await self.check_deadline()

    async def check_deadline(self) -> bool:
        """Resolve the round if its deadline has passed (the timer's final step; tests call it directly)."""
        async with self.lock:
            g = self.game
            if g is not None and g.status == ROUND_OPEN and g.effective_deadline() <= self.now():
                await self._resolve(timed_out=True)
                return True
            return False

    async def _maybe_early_resolve(self, g: TrainGame) -> bool:
        """Under the lock. Everyone in → resolve now (fugitive done or frozen) or start the fugitive's grace."""
        st = g.engine
        if not st.config.get("early_resolve", True) or not st.all_hunters_submitted():
            return False
        if st.fugitive.order is not None or st.fugitive.frozen:
            await self._resolve(timed_out=False)
            return True
        if g.policy.grace_until is None:
            g.policy.grace_until = min(g.policy.deadline_ts, self.now() + float(st.config["fugitive_grace_sec"]))
            await self._save()
            self._arm()
            await self._push({"type": "deadline", "deadline_ts": g.effective_deadline(), "reason": "grace"})
        return False

    async def _resolve(self, timed_out: bool) -> None:
        """Under the lock. Resolve the current round, snapshot, push role-filtered results, open the next round."""
        g = self.game
        st = g.engine
        report = E.resolve_round(st, timed_out=timed_out)
        entry = st.log[-1]
        pub = views.public_report(report)
        if st.status == CAPTURED:
            g.status = CAPTURED
            g.policy.grace_until = None
            g.policy.votes = {}
            await self._save()
            self._cancel_timer()
        else:
            g.status = ROUND_OPEN  # _open_round saves

        def build(pid: str) -> dict[str, Any]:
            if self.role_of(pid) == views.FUGITIVE:
                return {"type": "round_resolved", "report": report, "log_entry": entry, "state": self._payload(pid)}
            return {"type": "round_resolved", "report": pub, "state": self._payload(pid)}

        if st.status == CAPTURED:
            await hub.send_each(build)
            name = st.hunters[st.captured_by].name
            line = CAPTURE_LINE.format(name=name, particle=get_korean_particle(name, "이", "가"))
            await self._push({"type": "captured", "by": st.captured_by, "how": st.capture_how, "room": st.fugitive.room, "line": line})
            if not g.policy.webhook_sent:
                g.policy.webhook_sent = True
                await self._save()
                await self.webhook(line)
            return
        await self._open_round(g, push=False)   # the states inside round_resolved already carry the new deadline
        await hub.send_each(build)
        await self._push_round_open(g)

    # -- orders ----------------------------------------------------------------

    async def hunter_order(self, pid: str, order_type: str, target: str | None) -> dict[str, Any]:
        async with self.lock:
            g = self._require_game(ROUND_OPEN)
            st = g.engine
            try:
                o = E.submit_hunter_order(st, pid, order_type, target, now=self.now())
            except E.RuleError as e:
                raise _rule(e)
            if g.policy.votes.pop(pid, None) is not None:
                await self._push({"type": "vote", "target": pid, "voters": [], "need": g.votes_needed(), "passed": False, "void": True})
            await self._save()
            await self._push_submitted(g, pid, views.order_dict(o))
            await self._maybe_early_resolve(g)
            return {"order": views.order_dict(o)}

    async def cancel_hunter_order(self, pid: str) -> dict[str, Any]:
        async with self.lock:
            g = self._require_game(ROUND_OPEN)
            h = g.engine.hunters.get(pid)
            if h is None:
                raise ApiError(403, "not_hunter")
            h.order = None
            await self._save()
            await self._push_submitted(g, pid, None)
            return {"order": None}

    async def _push_submitted(self, g: TrainGame, pid: str, order: dict[str, Any] | None) -> None:
        st = g.engine
        pinged = st.fugitive.ping_round == st.round_no

        def build(to: str) -> dict[str, Any]:
            role = self.role_of(to)
            msg: dict[str, Any] = {"type": "submitted", "id": pid, "submitted": order is not None, "round": st.round_no}
            if role != views.FUGITIVE:
                msg["order"] = order
            elif pinged:
                # the post-ping stream: the fugitive paid for this round's orders, so later submits follow
                msg["order"] = order
                msg["type"] = "hunter_order"
            return msg

        await hub.send_each(build)

    async def fugitive_order(self, pid: str, move: str | None, hack: str | None, target: str | None) -> dict[str, Any]:
        self._require_admin(pid)
        async with self.lock:
            g = self._require_game(ROUND_OPEN)
            try:
                o = E.submit_fugitive_order(g.engine, move, hack, target, now=self.now())
            except E.RuleError as e:
                raise _rule(e)
            await self._save()
            resolved = await self._maybe_early_resolve(g)
            return {"order": views.forder_dict(o), "resolved": resolved}

    async def cancel_fugitive_order(self, pid: str) -> dict[str, Any]:
        self._require_admin(pid)
        async with self.lock:
            g = self._require_game(ROUND_OPEN)
            g.engine.fugitive.order = None
            await self._save()
            return {"order": None}

    async def ping(self, pid: str) -> dict[str, Any]:
        self._require_admin(pid)
        async with self.lock:
            g = self._require_game(ROUND_OPEN)
            st = g.engine
            try:
                E.cast_ping(st, now=self.now())
            except E.RuleError as e:
                raise _rule(e)
            await self._save()
            return {"orders": views.hunter_orders(st), "ram": st.fugitive.ram, "trace": st.fugitive.trace}

    # -- votes -----------------------------------------------------------------

    async def vote(self, pid: str, target: str) -> dict[str, Any]:
        async with self.lock:
            g = self._require_game(ROUND_OPEN)
            st = g.engine
            if pid not in st.hunters:
                raise ApiError(403, "not_hunter")
            after = g.vote_after_ts()
            if after is None or self.now() < after:
                raise ApiError(403, "vote_too_early")
            t = st.hunters.get(target)
            if target == pid or t is None or t.order is not None or t.dazed_until >= st.round_no:
                raise ApiError(400, "vote_bad_target")
            voters = g.policy.votes.setdefault(target, [])
            if pid not in voters:
                voters.append(pid)
            need = g.votes_needed()
            passed = len(voters) >= need
            if passed:
                E.submit_hunter_order(st, target, "stay", None, now=self.now())
                g.policy.votes.pop(target, None)
            await self._save()
            await self._push({"type": "vote", "target": target, "voters": list(voters), "need": need, "passed": passed})
            if passed:
                await self._push_submitted(g, target, {"type": "stay", "target": None})
                await self._maybe_early_resolve(g)
            return {"votes": list(voters), "need": need, "passed": passed}

    # -- admin: config / flow ----------------------------------------------------

    async def get_config(self, pid: str) -> dict[str, Any]:
        self._require_admin(pid)
        async with self.lock:
            g = self._require_game()
            return {"config": g.config(), "overrides": dict(g.policy.overrides), "map_id": g.policy.map_id,
                    "defaults": dict(E.cfgmod.DEFAULTS)}

    async def set_config(self, pid: str, values: dict[str, Any], map_id: str | None) -> dict[str, Any]:
        self._require_admin(pid)
        async with self.lock:
            g = self._require_game()
            if g.status in (CAPTURED, ENDED):
                raise ApiError(409, "not_open")
            if map_id is not None:
                if g.status != LOBBY:
                    raise ApiError(409, "map_locked")
                mid = E.cfgmod.normalize_map_id(map_id)
                if mid not in E.cfgmod.BUILTIN_MAPS:
                    raise ApiError(400, "unknown_map")
                g.policy.map_id = mid
            for k, v in values.items():
                try:
                    cv = E.cfgmod.coerce(k, v)
                except E.cfgmod.ConfigError as e:
                    raise RuleApiError(str(e), "bad_config")
                g.policy.overrides[k] = cv
                if g.engine is not None:
                    g.engine.config[k] = cv
            await self._save()
        await self._push_state()
        return await self.get_config(pid)

    async def pause(self, pid: str) -> dict[str, Any]:
        self._require_admin(pid)
        async with self.lock:
            g = self._require_game(ROUND_OPEN)
            g.policy.paused_remaining = max(0.0, g.effective_deadline() - self.now())
            g.policy.paused_at = self.now()
            g.policy.grace_until = None
            g.status = PAUSED
            g.engine.status = E.PAUSED
            g.engine.paused_remaining = g.policy.paused_remaining
            self._cancel_timer()
            await self._save()
            await self._push({"type": "paused", "paused_remaining": g.policy.paused_remaining})
            return {"paused_remaining": g.policy.paused_remaining}

    async def resume(self, pid: str) -> dict[str, Any]:
        self._require_admin(pid)
        async with self.lock:
            g = self._require_game(PAUSED)
            t = self.now()
            rem = float(g.policy.paused_remaining or 0.0)
            # shift the round's clock by the pause so the vote window opens the same number of played seconds in
            paused_for = max(0.0, t - (g.policy.paused_at if g.policy.paused_at is not None else t))
            g.policy.round_open_ts += paused_for
            g.policy.deadline_ts = t + rem
            g.policy.paused_remaining = None
            g.policy.paused_at = None
            g.status = ROUND_OPEN
            g.engine.status = E.ROUND_OPEN
            g.engine.paused_remaining = 0.0
            await self._save()
            self._arm()
            await self._push({"type": "resumed", "deadline_ts": g.policy.deadline_ts, "vote_after_ts": g.vote_after_ts()})
            return {"deadline_ts": g.policy.deadline_ts}

    async def extend(self, pid: str, sec: float) -> dict[str, Any]:
        self._require_admin(pid)
        async with self.lock:
            g = self._require_game(ROUND_OPEN, PAUSED)
            if g.status == PAUSED:
                g.policy.paused_remaining = float(g.policy.paused_remaining or 0.0) + sec
            else:
                g.policy.deadline_ts += sec
                self._arm()
            await self._save()
            await self._push({"type": "deadline", "deadline_ts": g.effective_deadline(), "reason": "extend",
                              "paused_remaining": g.policy.paused_remaining})
            return {"deadline_ts": g.policy.deadline_ts, "paused_remaining": g.policy.paused_remaining}

    async def end_round(self, pid: str) -> dict[str, Any]:
        self._require_admin(pid)
        async with self.lock:
            g = self._require_game(ROUND_OPEN, PAUSED)
            if g.status == PAUSED:
                g.engine.status = E.ROUND_OPEN
                g.status = ROUND_OPEN
            await self._resolve(timed_out=True)
            return self._payload(pid)

    async def end_game(self, pid: str) -> dict[str, Any]:
        self._require_admin(pid)
        async with self.lock:
            g = self._require_game()
            g.status = ENDED
            self._cancel_timer()
            await self._save()
            self.game = None
            await self._push({"type": "ended"})
        await self._push_state()
        return {"status": "IDLE"}

    # -- maps ------------------------------------------------------------------

    @staticmethod
    def maps() -> list[dict[str, Any]]:
        out = []
        for mid, rows in E.cfgmod.BUILTIN_MAPS.items():
            cols = max(c for (_d, _n, c, _r) in rows.values())
            rws = max(r for (_d, _n, _c, r) in rows.values())
            out.append({"id": mid, "rooms": len(rows), "cols": cols, "rows": rws})
        return out

    @staticmethod
    def map_detail(map_id: str) -> dict[str, Any]:
        mid = E.cfgmod.normalize_map_id(map_id)
        if mid not in E.cfgmod.BUILTIN_MAPS:
            raise ApiError(404, "unknown_map")
        gmap = E.GameMap.builtin(mid)
        return {"id": mid, "rooms": [{"id": r.id, "col": r.col, "row": r.row, "device": r.device, "neighbors": list(r.neighbors)}
                                     for r in gmap.rooms.values()]}
