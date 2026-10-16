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
from . import bot_player as B
from . import engine as E
from . import maps as train_maps
from . import settings, store, views
from .strings import CAPTURE_LINE, COMBAT_MODE_ON
from .utils import get_korean_particle
from .ws import hub

log = logging.getLogger("train")

LOBBY, ROUND_OPEN, PAUSED, CAPTURED, ENDED = "LOBBY", E.ROUND_OPEN, E.PAUSED, E.CAPTURED, store.ENDED
TIMER_CHUNK_S = 60.0
MIN_HUNTERS, MAX_HUNTERS = 2, 6
BOT_LOOK = {"preset": 0, "skin": 0, "eyes": 0, "hair": 0, "hair_color": 0, "outfit": 0, "acc": 0}   # AI hunters' avatar


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
    fugitive_ai: bool = False      # Gemini plays the fugitive; the admin keeps the controls and may ride as a hunter
    reveal_path: bool = False      # after CAPTURED: hunters/spectators may see the fugitive's whole route


@dataclass
class TrainGame:
    row_id: int | None
    status: str
    policy: Policy
    engine: E.GameState | None = None
    avatars: dict[str, dict[str, Any]] = field(default_factory=dict)   # shared with the Manager (not persisted)

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


Webhook = Callable[[str], Awaitable[Any]]
WEBHOOK_TIMEOUT_S = 4.0


async def post_webhook(line: str) -> bool:
    """Discord webhook: one line. Short timeout, never raises. False when nothing was delivered."""
    url = app_config.TRAIN_WEBHOOK_URL
    if not url:
        return False
    try:
        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT_S) as client:
            r = await client.post(url, json={"content": line})
            if r.status_code >= 300:
                log.warning("train webhook: HTTP %s", r.status_code)
                return False
            return True
    except Exception as e:  # noqa: BLE001
        log.warning("train webhook failed: %s", e)
        return False


class Manager:
    def __init__(self) -> None:
        self.game: TrainGame | None = None
        self.admin_id: str | None = None
        # AI hunters ("bot:N" lobby ids, bot_player.py from the Discord repo): decisions come from Gemini in a
        # background task per round; the reasons go to the fugitive only (like the bot's control channel)
        self.bot_player = B.GeminiPlayer()
        self.bot_task: asyncio.Task[None] | None = None
        self.fugitive_task: asyncio.Task[None] | None = None
        self.bot_task_round = -1
        self.fugitive_task_round = -1
        self.lock = asyncio.Lock()
        self._timer: asyncio.Task | None = None
        self.webhook: Webhook = post_webhook
        self.now: Callable[[], float] = time.time
        self.avatars: dict[str, dict[str, Any]] = {}   # hunter id → avatar look (public; the client draws them)

    # -- lifecycle -------------------------------------------------------------

    async def start(self) -> None:
        self.admin_id = await asyncio.to_thread(store.load_admin)
        row = await asyncio.to_thread(store.load_active_game)
        if row is not None:
            rid, status, snap = row
            try:
                self.game = TrainGame.from_snapshot(rid, status, snap)
                self.game.avatars = self.avatars
            except Exception as e:  # noqa: BLE001
                log.error("train: stored game %d unreadable, ending it: %s", rid, e)
                await asyncio.to_thread(store.save_snapshot, rid, ENDED, snap)
                self.game = None
        g = self.game
        if g is not None:
            await self._load_avatars(list(g.engine.hunters) if g.engine else g.policy.lobby)
        if g is not None and g.status == ROUND_OPEN:
            async with self.lock:
                if g.effective_deadline() <= self.now():
                    log.info("train: round %d expired while the server was down, resolving", g.engine.round_no)
                    await self._resolve(timed_out=True)
                else:
                    self._arm()
                    self._schedule_ai(g)
        elif g is not None:
            log.info("train: restored game %d (%s)", g.row_id, g.status)
            if g.status == CAPTURED and not g.policy.webhook_sent and g.engine is not None:
                self._fire_webhook(self._capture_line(g.engine), mark=True)  # the capture line never went out

    async def stop(self) -> None:
        self._cancel_timer()

    async def _load_avatars(self, pids: list[str]) -> None:
        def load() -> dict[str, dict[str, Any]]:
            from ..routers.me import load_avatar
            from ..db import connect
            conn = connect()
            try:
                return {pid: load_avatar(conn, pid) for pid in pids if not B.is_bot(pid)}
            finally:
                conn.close()
        self.avatars.update(await asyncio.to_thread(load))
        for pid in pids:
            if B.is_bot(pid):
                self.avatars[pid] = dict(BOT_LOOK)

    # -- roles -----------------------------------------------------------------

    def role_of(self, pid: str | None) -> str:
        g = self.game
        if pid is not None and pid == self.admin_id:
            # AI fugitive: the admin watches through the fugitive view unless they ride as a hunter themselves
            riding = g is not None and g.policy.fugitive_ai and (
                pid in g.engine.hunters if g.engine is not None else pid in g.policy.lobby)
            if not riding:
                return views.FUGITIVE
        if pid is not None and g is not None:
            if g.engine is not None and pid in g.engine.hunters:
                return views.HUNTER
            if g.engine is None and pid in g.policy.lobby:
                return views.HUNTER
        return views.SPECTATOR

    def _payload(self, pid: str | None) -> dict[str, Any]:
        role = self.role_of(pid)
        if self.game is None:
            return {"status": "IDLE", "role": role, "you": None, "ai_available": self.bot_player.available}
        out = views.payload_for(self.game, role, pid)
        out["ai_available"] = self.bot_player.available
        out["admin"] = pid is not None and pid == self.admin_id
        if self.game.status == CAPTURED and self.game.engine is not None:
            out["ai_log"] = list(self.game.engine.bot_reasons)   # every AI's reasoning, revealed once the chase is over
        return out

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

    # -- webhook (never on the resolve path: a background task after the snapshot is committed) -------------

    @staticmethod
    def _capture_line(st: E.GameState) -> str:
        name = st.hunters[st.captured_by].name
        return CAPTURE_LINE.format(name=name, particle=get_korean_particle(name, "이", "가"))

    def _fire_webhook(self, line: str, mark: bool) -> None:
        asyncio.create_task(self._webhook_task(line, mark))

    async def _webhook_task(self, line: str, mark: bool) -> None:
        try:
            ok = await self.webhook(line)
        except Exception as e:  # noqa: BLE001
            log.warning("train webhook raised: %s", e)
            ok = False
        if ok is False or not mark:
            return
        async with self.lock:
            g = self.game
            if g is not None and g.status == CAPTURED and not g.policy.webhook_sent:
                g.policy.webhook_sent = True
                await self._save()

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

    async def create(self, pid: str, hunter_count: int, map_id: str | None, overrides: dict[str, Any] | None,
                     fugitive_ai: bool = False) -> dict[str, Any]:
        """Anyone may open a game while none is running; the opener becomes that game's fugitive/admin
        (no secret needed — TRAIN_ADMIN_SECRET + /claim only re-binds the role, e.g. to take over a stuck game)."""
        if not MIN_HUNTERS <= hunter_count <= MAX_HUNTERS:
            raise ApiError(400, "bad_hunter_count")
        if fugitive_ai and not self.bot_player.available:
            raise ApiError(503, "ai_unavailable")
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
            if not train_maps.exists(mid):
                raise ApiError(400, "unknown_map")
            self.game = TrainGame(row_id=None, status=LOBBY,
                                  policy=Policy(hunter_count=hunter_count, map_id=mid, overrides=ov, fugitive_ai=fugitive_ai),
                                  avatars=self.avatars)
            if pid != self.admin_id:
                self.admin_id = pid
                await asyncio.to_thread(store.set_meta, "admin_id", pid)
            await self._save()
            out = self._payload(pid)
        await self._push_state()
        return out

    async def join(self, pid: str, joining: bool) -> dict[str, Any]:
        async with self.lock:
            g = self._require_game(LOBBY)
            if pid == self.admin_id and not g.policy.fugitive_ai:
                raise ApiError(403, "is_admin")
            if joining:
                if pid not in g.policy.lobby:
                    if len(g.policy.lobby) >= g.policy.hunter_count:
                        raise ApiError(409, "lobby_full")
                    g.policy.lobby.append(pid)
                    await self._load_avatars([pid])
            elif pid in g.policy.lobby:
                g.policy.lobby.remove(pid)
            await self._save()
            out = self._payload(pid)
        await self._push_state()
        return out

    async def add_bots(self, pid: str, target_count: int) -> dict[str, Any]:
        """Fill the lobby with AI hunters up to `target_count` (admin, LOBBY, needs GEMINI_API_KEY)."""
        self._require_admin(pid)
        async with self.lock:
            g = self._require_game(LOBBY)
            if not self.bot_player.available:
                raise ApiError(503, "ai_unavailable")
            target = min(max(target_count, MIN_HUNTERS), g.policy.hunter_count)
            need = target - len(g.policy.lobby)
            if need <= 0:
                raise ApiError(409, "lobby_full")
            existing = sum(1 for h in g.policy.lobby if B.is_bot(h))
            for uid, _name in B.bot_hunters(need, start=existing + 1):
                g.policy.lobby.append(uid)
            await self._load_avatars(g.policy.lobby)
            await self._save()
        await self._push_state()
        return self._payload(pid)

    async def set_fugitive_ai(self, pid: str, on: bool) -> dict[str, Any]:
        """Lobby only. Off → the admin leaves the lobby again (they become the fugitive)."""
        self._require_admin(pid)
        async with self.lock:
            g = self._require_game(LOBBY)
            if on and not self.bot_player.available:
                raise ApiError(503, "ai_unavailable")
            g.policy.fugitive_ai = on
            if not on and pid in g.policy.lobby:
                g.policy.lobby.remove(pid)
            await self._save()
        await self._push_state()
        return self._payload(pid)

    async def set_reveal(self, pid: str, on: bool) -> dict[str, Any]:
        """Post-game only: show everyone the fugitive's route (views adds `route` while CAPTURED and on)."""
        self._require_admin(pid)
        async with self.lock:
            g = self._require_game()
            if g.status != CAPTURED:
                raise ApiError(409, "not_captured")
            g.policy.reveal_path = on
            await self._save()
        await self._push_state()
        return self._payload(pid)

    async def remove_bots(self, pid: str) -> dict[str, Any]:
        self._require_admin(pid)
        async with self.lock:
            g = self._require_game(LOBBY)
            g.policy.lobby = [h for h in g.policy.lobby if not B.is_bot(h)]
            await self._save()
        await self._push_state()
        return self._payload(pid)

    # -- AI hunters: one background task per round, decisions outside the lock, submits under it ------------

    def _schedule_ai(self, g: TrainGame) -> None:
        self._schedule_bot_turn(g)
        self._schedule_fugitive_turn(g)

    def _schedule_fugitive_turn(self, g: TrainGame) -> None:
        st = g.engine
        if st is None or not st.debug_fugitive_ai or g.status != ROUND_OPEN or st.fugitive.order is not None:
            return
        if self.fugitive_task is not None and not self.fugitive_task.done():
            if self.fugitive_task_round == st.round_no:
                return
            self.fugitive_task.cancel()   # still waiting on Gemini for an earlier round: that answer is useless now
        self.fugitive_task_round = st.round_no
        self.fugitive_task = asyncio.create_task(self._run_fugitive_turn(g, st.round_no))

    async def _run_fugitive_turn(self, g: TrainGame, round_no: int) -> None:
        """Mirror of the bot's _run_fugitive_turn: Gemini decides outside the lock; a rule-breaking answer keeps the
        move and drops the hack, or waits."""
        st = g.engine
        await self._push_to_fugitive({"type": "bot_thinking", "id": B.FUGITIVE_UID, "round": round_no})
        try:
            d = await B.decide_fugitive(self.bot_player, st)
        except Exception:  # noqa: BLE001
            log.exception("train: AI fugitive R%d failed", round_no)
            return
        async with self.lock:
            if self.game is not g or g.status != ROUND_OPEN or st.round_no != round_no or st.fugitive.order is not None:
                return
            accepted, note = True, ""
            try:
                E.submit_fugitive_order(st, d.move, d.hack, d.target, now=self.now())
            except E.RuleError as e:
                accepted, note = False, str(e)
                try:
                    E.submit_fugitive_order(st, d.move, None, None, now=self.now())
                    note += " → 퀵핵 없이 이동만 제출"
                except E.RuleError:
                    E.submit_fugitive_order(st, None, None, None, now=self.now())
                    note += " → 대기"
            B.record_fugitive_reason(st, d, accepted, note)
            await self._push_to_fugitive({"type": "bot_reason", "reason": st.bot_reasons[-1]})
            await self._save()
            await self._push_fugitive_submitted(g)
            await self._maybe_early_resolve(g)

    def _schedule_bot_turn(self, g: TrainGame) -> None:
        st = g.engine
        if st is None or not st.debug_bots or g.status != ROUND_OPEN:
            return
        pending = [uid for uid in st.hunters if B.is_bot(uid) and st.hunters[uid].order is None
                   and st.hunters[uid].dazed_until < st.round_no]
        if not pending:
            return
        if self.bot_task is not None and not self.bot_task.done():
            if self.bot_task_round == st.round_no:
                return
            self.bot_task.cancel()
        self.bot_task_round = st.round_no
        self.bot_task = asyncio.create_task(self._run_bot_turn(g, st.round_no, pending))

    async def _run_bot_turn(self, g: TrainGame, round_no: int, uids: list[str]) -> None:
        st = g.engine
        for uid in uids:
            if self.game is not g or g.status != ROUND_OPEN or st.round_no != round_no:
                return
            if st.hunters[uid].order is not None:
                continue
            await self._push_to_fugitive({"type": "bot_thinking", "id": uid, "round": round_no})
            try:
                d = await self.bot_player.decide(st, uid)
            except Exception:  # noqa: BLE001
                log.exception("train: AI hunter %s R%d failed", uid, round_no)
                continue
            async with self.lock:
                if self.game is not g or g.status != ROUND_OPEN or st.round_no != round_no:
                    return
                if st.hunters[uid].order is not None:
                    continue
                accepted, note = True, ""
                try:
                    o = E.submit_hunter_order(st, uid, d.order, d.target, now=self.now())
                except E.RuleError as e:
                    accepted, note = False, str(e)
                    o = E.submit_hunter_order(st, uid, "stay", None, now=self.now())
                B.record_reason(st, uid, d, accepted, note)
                await self._push_to_fugitive({"type": "bot_reason", "reason": st.bot_reasons[-1]})
                if await self._after_hunter_submit(g, uid, o):
                    return   # the round resolved; the next round's open scheduled a fresh task

    async def _push_fugitive_submitted(self, g: TrainGame) -> None:
        """Everyone learns WHETHER the fugitive has submitted (never what): hunters need it to read a stalled round."""
        await self._push({"type": "fugitive_submitted", "submitted": g.engine.fugitive.order is not None, "round": g.engine.round_no})

    async def _push_to_fugitive(self, msg: dict[str, Any]) -> None:
        await hub.send_each(lambda pid: msg if self.role_of(pid) == views.FUGITIVE else None)

    async def start_game(self, pid: str) -> dict[str, Any]:
        self._require_admin(pid)
        async with self.lock:
            g = self._require_game(LOBBY)
            if len(g.policy.lobby) < MIN_HUNTERS:
                raise ApiError(409, "not_enough_hunters")
            cfg, _ = settings.build(g.policy.hunter_count, g.policy.overrides)
            gmap = train_maps.game_map(g.policy.map_id)
            if gmap is None:   # the map was removed from data/train_maps.json after the lobby picked it
                raise ApiError(409, "unknown_map")
            try:
                g.engine = E.new_game(gmap, cfg, [(h, h) for h in g.policy.lobby], now=self.now())
            except E.RuleError as e:
                raise _rule(e)
            g.engine.debug_bots = any(B.is_bot(h) for h in g.policy.lobby)
            g.engine.debug_fugitive_ai = g.policy.fugitive_ai
            await self._open_round(g, push=False)
            out = self._payload(pid)
            await self._push({"type": "started", "line": COMBAT_MODE_ON})
            await self._push_state()
            await self._push_round_open(g)
        self._fire_webhook(COMBAT_MODE_ON, mark=False)
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
        self._schedule_ai(g)

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
            line = self._capture_line(st)
            await self._push({"type": "captured", "by": st.captured_by, "how": st.capture_how, "room": st.fugitive.room, "line": line})
            if not g.policy.webhook_sent:
                self._fire_webhook(line, mark=True)  # webhook_sent is set only once the POST succeeded
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
            await self._after_hunter_submit(g, pid, o)
            return {"order": views.order_dict(o)}

    async def _after_hunter_submit(self, g: TrainGame, pid: str, o: Any) -> bool:
        """Under the lock, after a hunter's order went into the engine: void a pending vote against them, snapshot,
        tell everyone, maybe resolve early. Returns True when the round was resolved."""
        if g.policy.votes.pop(pid, None) is not None:
            await self._push({"type": "vote", "target": pid, "voters": [], "need": g.votes_needed(), "passed": False, "void": True})
        await self._save()
        await self._push_submitted(g, pid, views.order_dict(o))
        return await self._maybe_early_resolve(g)

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
            if g.policy.fugitive_ai:
                raise ApiError(403, "fugitive_is_ai")
            g = self._require_game(ROUND_OPEN)
            try:
                o = E.submit_fugitive_order(g.engine, move, hack, target, now=self.now())
            except E.RuleError as e:
                raise _rule(e)
            await self._save()
            await self._push_fugitive_submitted(g)
            resolved = await self._maybe_early_resolve(g)
            return {"order": views.forder_dict(o), "resolved": resolved}

    async def cancel_fugitive_order(self, pid: str) -> dict[str, Any]:
        self._require_admin(pid)
        async with self.lock:
            g = self._require_game(ROUND_OPEN)
            if g.policy.fugitive_ai:
                raise ApiError(403, "fugitive_is_ai")
            g = self._require_game(ROUND_OPEN)
            g.engine.fugitive.order = None
            await self._save()
            await self._push_fugitive_submitted(g)
            return {"order": None}

    async def ping(self, pid: str) -> dict[str, Any]:
        self._require_admin(pid)
        async with self.lock:
            g = self._require_game(ROUND_OPEN)
            if g.policy.fugitive_ai:
                raise ApiError(403, "fugitive_is_ai")
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

    async def set_config(self, pid: str, values: dict[str, Any], map_id: str | None, reset: bool = False) -> dict[str, Any]:
        self._require_admin(pid)
        async with self.lock:
            g = self._require_game()
            if g.status in (CAPTURED, ENDED):
                raise ApiError(409, "not_open")
            if reset and g.policy.overrides:
                # back to DEFAULTS ⊕ scaling ⊕ train_config.json for every key the admin had overridden
                base, _ = settings.build(g.policy.hunter_count, {})
                if g.engine is not None:
                    for k in g.policy.overrides:
                        if k in base:
                            g.engine.config[k] = base[k]
                        else:
                            g.engine.config.pop(k, None)
                g.policy.overrides = {}
            if map_id is not None:
                if g.status != LOBBY:
                    raise ApiError(409, "map_locked")
                mid = E.cfgmod.normalize_map_id(map_id)
                if not train_maps.exists(mid):
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
            self._schedule_ai(g)
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
        for mid, rows in train_maps.all_maps().items():
            cols = max(int(r["col"]) for r in rows)
            rws = max(int(r["row"]) for r in rows)
            out.append({"id": mid, "rooms": len(rows), "cols": cols, "rows": rws})
        return out

    @staticmethod
    def map_detail(map_id: str) -> dict[str, Any]:
        mid = E.cfgmod.normalize_map_id(map_id)
        gmap = train_maps.game_map(mid)
        if gmap is None:
            raise ApiError(404, "unknown_map")
        return {"id": mid, "rooms": [{"id": r.id, "col": r.col, "row": r.row, "device": r.device, "neighbors": list(r.neighbors)}
                                     for r in gmap.rooms.values()]}
