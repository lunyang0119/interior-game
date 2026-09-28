"""Dock fishing: the server makes the bite schedule and judges the holds (plan §Phase 4).

A cast = `bites` bites. For each bite the player presses "낚아올리기" inside its window and keeps holding for
that bite's `hold_ms` (random per bite) to pull it up; a press while no bite is up scares the fish away.
The number of pulls picks the catch chance (`catch_pct[pulls]`).
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

from pydantic import BaseModel, Field, model_validator

from . import config
from .errors import ApiError

SESSION_TTL_S = 90.0


class Loot(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str
    value: int = Field(ge=1)
    weight: int = Field(ge=1)
    icon: str | None = None  # asset path (build copies it to gen/fish/<id>.png)


class FishingConfig(BaseModel):
    bites: int = Field(ge=1, default=3)
    gap_ms: tuple[int, int] = (900, 1800)
    window_ms: tuple[int, int] = (500, 1000)
    hold_ms: tuple[int, int] = (1000, 5000)  # per bite: how long the press must last to pull it up
    # catch chance (%) by number of successful pulls, index 0..bites
    catch_pct: list[int] = Field(default_factory=lambda: [0, 0, 50, 100])
    slack_ms: int = 250
    cooldown_s: int = 3
    loot: list[Loot]

    @model_validator(mode="after")
    def _pct(self) -> "FishingConfig":
        if len(self.catch_pct) != self.bites + 1 or any(not 0 <= p <= 100 for p in self.catch_pct):
            raise ValueError("fishing.json: catch_pct needs bites+1 entries in 0..100")
        return self

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
    window_ms: int  # the press has to start inside [at_ms, at_ms + window_ms]
    hold_ms: int  # ...and last this long


@dataclass
class Session:
    id: str
    player_id: str
    t0: float  # monotonic seconds when the schedule was handed out
    bites: list[Bite]
    loot: Loot
    done: bool = False

    def public(self) -> dict:
        return {"session": self.id,
                "bites": [{"at_ms": b.at_ms, "window_ms": b.window_ms, "hold_ms": b.hold_ms} for b in self.bites]}


@dataclass
class HoldSpan:
    start_ms: int
    end_ms: int


@dataclass
class Result:
    ok: bool
    pulls: int
    escaped: bool


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
            t = 0
            bites: list[Bite] = []
            for _ in range(self.cfg.bites):
                t += self.rng.randint(*self.cfg.gap_ms)
                w = self.rng.randint(*self.cfg.window_ms)
                h = self.rng.randint(*self.cfg.hold_ms)
                bites.append(Bite(at_ms=t, window_ms=w, hold_ms=h))
                t += w + h  # room for a hold started at the very end of the window
            s = Session(id=secrets.token_urlsafe(12), player_id=player_id, t0=now, bites=bites, loot=loot)
            self.sessions[s.id] = s
            return s

    # -- judgement ---------------------------------------------------------------

    def judge(self, s: Session, holds: list[HoldSpan]) -> tuple[int, bool]:
        """(pulls, escaped). Each press must start in the window of a bite not tried yet; it pulls that bite up if
        it lasted the bite's hold_ms, otherwise that bite is lost. Any other press (no bite up, or a second press
        on the same bite) scares the fish away."""
        slack = self.cfg.slack_ms
        tried: set[int] = set()
        pulls = 0
        for h in sorted(holds, key=lambda h: h.start_ms):
            i = next((i for i, b in enumerate(s.bites)
                      if i not in tried and b.at_ms - slack <= h.start_ms <= b.at_ms + b.window_ms + slack), None)
            if i is None:
                return pulls, True
            tried.add(i)
            if h.end_ms - h.start_ms >= s.bites[i].hold_ms - slack:
                pulls += 1
        return pulls, False

    def finish(self, player_id: str, session_id: str, holds: list[HoldSpan], gave_up: bool = False) -> tuple[Session, Result]:
        """`gave_up`: the client saw the fish escape and ended the cast early. Ending before the last bite's window
        (or the last reported hold) is over counts as an escape too, so an early finish can never pay out."""
        now = time.monotonic()
        with self.lock:
            s = self.sessions.get(session_id)
            if s is None or s.player_id != player_id or s.done:
                raise ApiError(400, "no_session")
            s.done = True
            self.last_finish[player_id] = now
            pulls, escaped = self.judge(s, holds)
            last = s.bites[-1]
            done_ms = max([last.at_ms + last.window_ms] + [h.end_ms for h in holds])
            escaped = escaped or gave_up or (now - s.t0) * 1000 < done_ms - self.cfg.slack_ms
            ok = not escaped and self.rng.randrange(100) < self.cfg.catch_pct[pulls]
            del self.sessions[session_id]
            return s, Result(ok=ok, pulls=pulls, escaped=escaped)
