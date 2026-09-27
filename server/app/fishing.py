"""Dock fishing: the server makes the bite schedule and judges the holds (plan §Phase 4).

A cast = `bites` nibbles; exactly one is the real bite. The player must press during the real bite's
window and keep holding `hold_ms` (longer for pricier fish). Pressing during a fake nibble scares the fish.
The client only reports when it held the button; the reward goes straight into the shared pool (no inventory).
Sessions live in memory (one worker) and expire after SESSION_TTL_S.
"""

from __future__ import annotations

import json
import random
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from . import config
from .errors import ApiError

SESSION_TTL_S = 90.0


class Loot(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str
    value: int = Field(ge=1)
    weight: int = Field(ge=1)
    icon: str | None = None  # asset path (build copies it to gen/fish/<id>.png)


class Hold(BaseModel):
    base_ms: int = 300
    per_value_ms: int = 6
    max_ms: int = 1500


class FishingConfig(BaseModel):
    bites: int = Field(ge=1, default=5)
    gap_ms: tuple[int, int] = (900, 1800)
    window_ms: tuple[int, int] = (500, 1000)
    hold: Hold = Hold()
    slack_ms: int = 250
    cooldown_s: int = 3
    loot: list[Loot]

    def hold_ms(self, value: int) -> int:
        return min(self.hold.max_ms, self.hold.base_ms + value * self.hold.per_value_ms)

    def public(self) -> dict:
        return {"loot": [{"id": l.id, "name": l.name, "value": l.value} for l in self.loot], "cooldown_s": self.cooldown_s}


def load_config(path: Path | None = None) -> FishingConfig:
    p = path or (config.DATA_DIR / "fishing.json")
    cfg = FishingConfig.model_validate(json.loads(p.read_text(encoding="utf-8")))
    ids = [l.id for l in cfg.loot]
    if len(set(ids)) != len(ids):
        raise ValueError("fishing.json: duplicate loot id")
    return cfg


@dataclass
class Bite:
    at_ms: int
    window_ms: int
    real: bool


@dataclass
class Session:
    id: str
    player_id: str
    t0: float  # monotonic seconds when the schedule was handed out
    bites: list[Bite]
    loot: Loot
    hold_ms: int
    done: bool = False

    @property
    def real(self) -> Bite:
        return next(b for b in self.bites if b.real)

    def public(self) -> dict:
        return {"session": self.id, "hold_ms": self.hold_ms,
                "bites": [{"at_ms": b.at_ms, "window_ms": b.window_ms, "real": b.real} for b in self.bites]}


@dataclass
class HoldSpan:
    start_ms: int
    end_ms: int


@dataclass
class Fishing:
    cfg: FishingConfig
    rng: random.Random = field(default_factory=random.Random)
    sessions: dict[str, Session] = field(default_factory=dict)
    last_finish: dict[str, float] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    # -- schedule --------------------------------------------------------------

    def _prune(self, now: float) -> None:
        for sid, s in list(self.sessions.items()):
            if now - s.t0 > SESSION_TTL_S:
                del self.sessions[sid]

    def start(self, player_id: str) -> Session:
        now = time.monotonic()
        with self.lock:
            self._prune(now)
            if now - self.last_finish.get(player_id, -1e9) < self.cfg.cooldown_s:
                raise ApiError(429, "fish_cooldown")
            for s in self.sessions.values():
                if s.player_id == player_id and not s.done:
                    del self.sessions[s.id]  # a new cast abandons the previous one
                    break
            loot = self.rng.choices(self.cfg.loot, weights=[l.weight for l in self.cfg.loot])[0]
            real = self.rng.randrange(self.cfg.bites)
            t = 0
            bites: list[Bite] = []
            for i in range(self.cfg.bites):
                t += self.rng.randint(*self.cfg.gap_ms)
                w = self.rng.randint(*self.cfg.window_ms)
                bites.append(Bite(at_ms=t, window_ms=w, real=i == real))
                t += w
            s = Session(id=secrets.token_urlsafe(12), player_id=player_id, t0=now, bites=bites, loot=loot,
                        hold_ms=self.cfg.hold_ms(loot.value))
            self.sessions[s.id] = s
            return s

    # -- judgement ---------------------------------------------------------------

    def judge(self, s: Session, holds: list[HoldSpan]) -> bool:
        slack = self.cfg.slack_ms
        for b in s.bites:
            if b.real:
                continue
            # a press inside a fake nibble's window scares the fish away
            if any(b.at_ms - slack <= h.start_ms <= b.at_ms + b.window_ms + slack for h in holds):
                return False
        r = s.real
        for h in holds:
            if h.end_ms - h.start_ms < s.hold_ms:
                continue
            if h.start_ms >= r.at_ms - slack and h.start_ms <= r.at_ms + r.window_ms + slack:
                return True
        return False

    def finish(self, player_id: str, session_id: str, holds: list[HoldSpan]) -> tuple[Session, bool]:
        now = time.monotonic()
        with self.lock:
            s = self.sessions.get(session_id)
            if s is None or s.player_id != player_id or s.done:
                raise ApiError(400, "no_session")
            r = s.real
            if (now - s.t0) * 1000 < r.at_ms + r.window_ms - self.cfg.slack_ms:
                raise ApiError(400, "too_early")
            s.done = True
            self.last_finish[player_id] = now
            ok = self.judge(s, holds)
            del self.sessions[session_id]
            return s, ok
