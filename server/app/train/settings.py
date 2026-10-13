"""Effective engine config for the web port.

Layers, later wins:  engine DEFAULTS → web defaults (1-hour rounds, early resolve) → scaling_web.json[hunter_count]
(also picks the map) → data/train_config.json (optional, same shape as the bot's Fugitive_Config: {key: value}) →
admin runtime overrides. Every value goes through config.coerce so types match DEFAULTS. No Google Sheet.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .. import config as app_config
from . import config as cfg

log = logging.getLogger("train.settings")

WEB_DEFAULTS: dict[str, Any] = {"round_timer_sec": 3600, "early_resolve": True}
# keys the engine never reads: the server's round policy
POLICY_KEYS = ("round_timer_sec", "fugitive_grace_sec", "early_resolve", "vote_skip_after_sec")
# tunables the hunter/spectator payload may carry (nothing about the fugitive's resources)
PUBLIC_KEYS = (*POLICY_KEYS, "scan_budget", "max_rounds", "fugitive_speed", "capture_mode", "signal_mode", "hunter_colors")

SCALING_PATH = Path(__file__).with_name("scaling_web.json")


def load_scaling(path: Path = SCALING_PATH) -> dict[int, dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {int(k): dict(v) for k, v in raw.items() if str(k).strip().isdigit()}


def load_file_overrides(path: Path | None = None) -> dict[str, Any]:
    p = path or app_config.TRAIN_CONFIG_PATH
    if not p.exists():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8"))
    out: dict[str, Any] = {}
    for k, v in raw.items():
        if str(k).startswith("_"):
            continue
        if k not in cfg.DEFAULTS:
            log.warning("train_config.json: unknown key ignored: %s", k)
            continue
        out[k] = cfg.coerce(k, v)
    return out


def build(hunter_count: int, overrides: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
    """(effective config, map_id). `overrides` are the admin's runtime values (already coerced or raw)."""
    scaling = load_scaling()
    c, map_id = cfg.build_config(hunter_count, sheet_config=None, sheet_scaling=scaling)
    for k, v in WEB_DEFAULTS.items():
        c[k] = cfg.coerce(k, v)
    c.update(load_file_overrides())
    for k, v in (overrides or {}).items():
        c[k] = cfg.coerce(k, v)
    return c, map_id


def default_map_id(hunter_count: int) -> str:
    scaling = load_scaling()
    n = max(min(hunter_count, max(scaling)), min(scaling))
    return str(scaling[n].get("map_id", "car2077_12"))


def public_config(c: dict[str, Any]) -> dict[str, Any]:
    return {k: c[k] for k in PUBLIC_KEYS if k in c}
