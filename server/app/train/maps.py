"""Train maps the web port can play: the engine's BUILTIN_MAPS plus data/train_maps.json.

The file is edited in the preprocess editor (/train-maps). A file map with a built-in's id replaces that built-in.
Shape: {"maps": {map_id: [{room, device, neighbors: "A2,B1", col, row}, ...]}} — the rows of the bot's Fugitive_Map
sheet. Every map goes through the engine's GameMap.validate (devices, symmetric neighbours, no same-device neighbours,
connected); on top of that the web layout (client/src/train/render/layout.ts) only draws a door between grid
neighbours, so a neighbour must sit one step left/right/up/down and no two rooms may share a cell. A bad file map is
logged and skipped, never fatal. A running game keeps its own copy of the map rows (engine state), so edits only
affect games opened afterwards.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from .. import config as app_config
from . import config as cfgmod
from . import engine as E

log = logging.getLogger("train.maps")

MAP_ID_RE = re.compile(r"^[a-z0-9_]{1,32}$")
# edge keys are "A1-A2", so no '-' or ','; uppercase only: the AI fugitive's answer parser upper-cases room ids
ROOM_ID_RE = re.compile(r"^[A-Z0-9_]{1,8}$")
MAX_GRID = 8

_cache: dict[str, Any] = {}


def _row(r: dict[str, Any]) -> dict[str, Any]:
    nb = r.get("neighbors", "")
    if isinstance(nb, list):
        nb = ",".join(str(x) for x in nb)
    return {"room": str(r.get("room", "")).strip(), "device": str(r.get("device", "")).strip(),
            "neighbors": str(nb).replace(" ", ""), "col": r.get("col"), "row": r.get("row")}


def validate(map_id: str, rows: list[dict[str, Any]]) -> str | None:
    """Why this map cannot be played (Korean, for the editor), or None."""
    if not MAP_ID_RE.match(map_id or ""):
        return f"맵 id '{map_id}'는 영문 소문자/숫자/_ 32자 이하여야 해요"
    if not isinstance(rows, list) or len(rows) < 2:
        return f"{map_id}: 방이 2개 이상 있어야 해요"
    rows = [_row(r) for r in rows if isinstance(r, dict)]
    seen: set[str] = set()
    pos: dict[tuple[int, int], str] = {}
    for r in rows:
        rid = r["room"]
        if not ROOM_ID_RE.match(rid):
            return f"{map_id}: 방 id '{rid}'는 영문 대문자/숫자/_ 8자 이하여야 해요"
        if rid in seen:
            return f"{map_id}: 방 id {rid}가 겹쳐요"
        seen.add(rid)
        c, rw = r["col"], r["row"]
        if not all(isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= MAX_GRID for v in (c, rw)):
            return f"{map_id}: {rid}의 col/row는 1~{MAX_GRID} 정수여야 해요"
        if (c, rw) in pos:
            return f"{map_id}: {rid}와 {pos[(c, rw)]}가 같은 칸에 있어요"
        pos[(c, rw)] = rid
    try:
        gmap = E.GameMap.from_rows(map_id, rows)
    except cfgmod.ConfigError as e:
        return f"{map_id}: {e}"
    for r in gmap.rooms.values():
        for n in r.neighbors:
            o = gmap.rooms[n]
            if abs(r.col - o.col) + abs(r.row - o.row) != 1:
                return f"{map_id}: {r.id}-{n}는 바로 옆(상하좌우) 방이 아니라 문을 그릴 수 없어요"
    return None


def load_file(path: Path | None = None) -> dict[str, list[dict[str, Any]]]:
    """Valid maps of data/train_maps.json (re-read when the file changes)."""
    p = path or app_config.TRAIN_MAPS_PATH
    if not p.exists():
        return {}
    mtime = p.stat().st_mtime
    if _cache.get("key") == (str(p), mtime):
        return _cache["maps"]
    out: dict[str, list[dict[str, Any]]] = {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8")).get("maps") or {}
    except (json.JSONDecodeError, AttributeError) as e:
        log.warning("train_maps.json unreadable, ignored: %s", e)
        raw = {}
    for mid, rows in raw.items():
        err = validate(mid, rows)
        if err:
            log.warning("train_maps.json: map skipped: %s", err)
            continue
        out[mid] = [_row(r) for r in rows]
    _cache.update(key=(str(p), mtime), maps=out)
    return out


def builtin_rows() -> dict[str, list[dict[str, Any]]]:
    return {mid: [_row(r) for r in cfgmod.map_rows(mid)] for mid in cfgmod.BUILTIN_MAPS}


def all_maps() -> dict[str, list[dict[str, Any]]]:
    """map id → rows; built-ins first, the file's maps replace/extend them."""
    return {**builtin_rows(), **load_file()}


def exists(map_id: str) -> bool:
    return map_id in all_maps()


def game_map(map_id: str) -> E.GameMap | None:
    rows = all_maps().get(map_id)
    return E.GameMap.from_rows(map_id, rows) if rows else None
