"""Effective engine config for the web port.

Layers, later wins:
  engine DEFAULTS → scaling_web.json[n] (also picks the map) → WEB_DEFAULTS (1-hour rounds, early resolve, ping
  signature, escape on freeze) → data/train_config.json flat keys → data/train_config.json["n"] (per-seat section)
  → admin runtime overrides.
`n` is the number of hunters the game is scaled for: the boarding count at start (clamped to the scaling table),
not the seat count chosen when the lobby was opened. Every value goes through coerce() so types match DEFAULTS;
validate() rejects values the engine or the round policy cannot run with. No Google Sheet.
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import config as app_config
from . import config as cfg

if TYPE_CHECKING:
    from .engine import GameMap

log = logging.getLogger("train.settings")

# keys only the web port knows (the engine's coerce() rejects them): name → default
WEB_ONLY: dict[str, Any] = {
    # the fugitive wins when the safety freeze hits before anyone caught them (manager status ESCAPED)
    "escape_on_freeze": True,
}
WEB_DEFAULTS: dict[str, Any] = {"round_timer_sec": 3600, "early_resolve": True,
                                # the hunters' report shows the ping signature, as the help text promises (F04)
                                "ping_signature": True, **WEB_ONLY}
# keys the engine never reads: the server's round policy
POLICY_KEYS = ("round_timer_sec", "fugitive_grace_sec", "early_resolve", "vote_skip_after_sec", "escape_on_freeze")
# tunables the hunter/spectator payload may carry (nothing about the fugitive's resources). The trace tiers, signal
# bands, scan lag and overheat length let the client explain the tracker (marker age, candidate rooms, escape countdown).
PUBLIC_KEYS = (*POLICY_KEYS, "scan_budget", "scan_lag", "max_rounds", "overheat_rounds", "fugitive_speed", "capture_mode",
               "signal_mode", "signal_bands", "trace_t1", "trace_t2", "trace_t3", "hunter_colors")

SCALING_PATH = Path(__file__).with_name("scaling_web.json")

_TRUE = ("1", "true", "t", "yes", "y", "on", "참")
_FALSE = ("0", "false", "f", "no", "n", "off", "거짓")


class ConfigError(cfg.ConfigError):
    pass


def known(key: str) -> bool:
    return key in cfg.DEFAULTS or key in WEB_ONLY


def all_defaults() -> dict[str, Any]:
    return {**cfg.DEFAULTS, **WEB_ONLY}


def coerce(key: str, raw: Any) -> Any:
    """config.coerce plus the web-only keys (all booleans so far)."""
    if key in WEB_ONLY:
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        if s in _TRUE:
            return True
        if s in _FALSE:
            return False
        raise ConfigError(f"{key}: 참/거짓 값이어야 해요 ({raw!r})")
    return cfg.coerce(key, raw)


def load_scaling(path: Path = SCALING_PATH) -> dict[int, dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {int(k): dict(v) for k, v in raw.items() if str(k).strip().isdigit()}


def clamp_seats(n: int, scaling: dict[int, Any] | None = None) -> int:
    s = scaling or load_scaling()
    return max(min(int(n), max(s)), min(s))


def _section(raw: dict[str, Any], where: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in raw.items():
        if str(k).startswith("_"):
            continue
        if not known(k):
            log.warning("train_config.json%s: unknown key ignored: %s", where, k)
            continue
        out[k] = coerce(k, v)
    return out


def load_file_overrides(path: Path | None = None, hunter_count: int | None = None) -> dict[str, Any]:
    """data/train_config.json: flat {key: value} for every game, then the per-seat section {"2".."6": {key: value}}
    for `hunter_count` (clamped like the scaling table) on top. Keys starting with '_' are comments."""
    p = path or app_config.TRAIN_CONFIG_PATH
    if not p.exists():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8"))
    flat = {k: v for k, v in raw.items() if not str(k).strip().isdigit()}
    out = _section(flat, "")
    if hunter_count is not None:
        seats = {int(k): v for k, v in raw.items() if str(k).strip().isdigit() and isinstance(v, dict)}
        if seats:
            n = max(min(int(hunter_count), max(seats)), min(seats))
            out.update(_section(seats.get(n, {}), f'["{n}"]'))
    return out


def build(hunter_count: int, overrides: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
    """(effective config, map_id) for a game scaled for `hunter_count`. `overrides` = the admin's runtime values."""
    scaling = load_scaling()
    c, map_id = cfg.build_config(hunter_count, sheet_config=None, sheet_scaling=scaling)
    for k, v in WEB_DEFAULTS.items():
        c[k] = coerce(k, v)
    c.update(load_file_overrides(hunter_count=hunter_count))
    for k, v in (overrides or {}).items():
        c[k] = coerce(k, v)
    return c, map_id


def default_map_id(hunter_count: int) -> str:
    scaling = load_scaling()
    return str(scaling[clamp_seats(hunter_count, scaling)].get("map_id", "car2077_12"))


def public_config(c: dict[str, Any]) -> dict[str, Any]:
    return {k: c[k] for k in PUBLIC_KEYS if k in c}


# -- validation ---------------------------------------------------------------------------------------------

_MIN: dict[str, int | float] = {
    "round_timer_sec": 60, "fugitive_grace_sec": 0, "vote_skip_after_sec": 0,
    "trace_passive": 0, "scan_trace": 0, "ram_max": 1, "ram_regen": 0, "max_rounds": 1, "overheat_rounds": 0,
    "scan_budget": 0, "scan_lag": 0, "fugitive_speed": 1, "hide_duration": 1, "overload_daze_rounds": 0,
    "doorlock_range": -1, "trace_t1": 0, "trace_t2": 0, "trace_t3": 1,
}


def validate(c: dict[str, Any], gmap: "GameMap | None" = None) -> None:
    """Raise ConfigError (Korean) for a value the engine or the round policy cannot run with. `gmap` checks the
    placement keys against the rooms of the map the game is (or will be) played on."""
    for k, lo in _MIN.items():
        if k in c and c[k] < lo:
            raise ConfigError(f"{k}: {lo} 이상이어야 해요 ({c[k]})")
    for k, v in c.items():
        if (k.endswith("_trace") or k.endswith("_cost")) and isinstance(v, (int, float)) and not isinstance(v, bool) and v < 0:
            raise ConfigError(f"{k}: 0 이상이어야 해요 ({v})")
    if "contact_capture_chance" in c and not 0.0 <= float(c["contact_capture_chance"]) <= 1.0:
        raise ConfigError("contact_capture_chance: 0~1 사이여야 해요")
    if all(k in c for k in ("trace_t1", "trace_t2", "trace_t3")) and not c["trace_t1"] <= c["trace_t2"] <= c["trace_t3"]:
        raise ConfigError("trace_t1 ≤ trace_t2 ≤ trace_t3 이어야 해요")
    if "signal_bands" in c:
        parts = str(c["signal_bands"]).replace(" ", "").split(",")
        try:
            a, b = (int(x) for x in parts)
        except ValueError:
            raise ConfigError(f"signal_bands: '강,중' 거리 두 개를 쉼표로 적어 주세요 (예: 1,2) ({c['signal_bands']!r})")
        if not 0 <= a < b:
            raise ConfigError(f"signal_bands: 0 ≤ 첫 값 < 둘째 값이어야 해요 ({c['signal_bands']!r})")
    if gmap is not None:
        start = str(c.get("fugitive_start", "auto"))
        if start != "auto" and start not in gmap.rooms:
            raise ConfigError(f"fugitive_start: {start}는 맵 {gmap.map_id}에 없는 구역이에요")
        spawns = str(c.get("hunter_spawn_rooms", "auto"))
        if spawns != "auto":
            pool = [x for x in spawns.replace(" ", "").split(",") if x]
            bad = [x for x in pool if x not in gmap.rooms]
            if not pool or bad:
                raise ConfigError(f"hunter_spawn_rooms: 맵 {gmap.map_id}에 없는 구역이 있어요 ({', '.join(bad) or '비어 있음'})")


# -- start placement (F12) ------------------------------------------------------------------------------------

def placement(gmap: "GameMap", n_hunters: int, c: dict[str, Any], rng: random.Random) -> tuple[str, str]:
    """(fugitive_start, hunter_spawn_rooms) for a new game. 'auto' values are randomised per game: the fugitive
    starts in a random room whose eccentricity is within min+1, the hunters spawn on the farthest rooms from it
    (ties broken at random, then shuffled) — the engine's own 'auto' always picks the same rooms. Explicit admin
    values are kept as they are."""
    rooms = sorted(gmap.rooms)
    start = str(c.get("fugitive_start", "auto"))
    if start == "auto":
        ecc = {r: max(gmap.distance(r, o) for o in rooms) for r in rooms}
        lo = min(ecc.values())
        start = rng.choice([r for r in rooms if ecc[r] <= lo + 1])
    spawns = str(c.get("hunter_spawn_rooms", "auto"))
    if spawns == "auto":
        ranked = sorted(rooms, key=lambda r: (-gmap.distance(start, r), rng.random()))
        far = ranked[: max(1, min(n_hunters, len(ranked) // 2))]
        rng.shuffle(far)
        spawns = ",".join(far)
    return start, spawns
