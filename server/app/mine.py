"""The mine: ore nodes spawned once per KST calendar day, mined by walking up and pressing 채광.

data/mine.json names the mine room (a grid room with `kind: "mine"`), how many nodes a day gets (`per_day`:
the daily cap the UI states), the ore kinds (hits needed, value, spawn weight, icon crop for `build`) and the
per-player hit cooldown. Every node is shared: each `POST /api/mine/hit` takes one off its hits_left and the
hit that empties it pays the shared pool (ledger.kind='mine') in that player's name, like a fish catch —
deliverable within the same window. Nodes never carry over: at midnight a fresh set appears, whether or not
yesterday's were mined (room_meta 'mine_day:<room>' makes the spawn idempotent, like guest days).

Like fishing.py the config is pure pydantic; the DB side lives here too (spawn/nodes/hit) because it is small.
"""

from __future__ import annotations

import json
import math
import random
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, model_validator

from . import config
from .db import now
from .errors import ApiError
from .items import load_items
from .placement import footprint_of

if TYPE_CHECKING:
    from .catalog import Catalog

KST = timezone(timedelta(hours=9))
LEDGER_KIND = "mine"
ROOM_KIND = "mine"  # catalog.Room.kind of the mine room


class IconCrop(BaseModel):
    """A 16x16 cell of a sprite sheet under assets/graphic (build crops it to gen/mine/<id>.png)."""
    file: str
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(ge=1, default=16)
    h: int = Field(ge=1, default=16)


class Ore(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str
    hits: int = Field(ge=1)  # presses of 채광 to break it
    value: int = Field(ge=0)  # money into the pool when it breaks (0 = a dud)
    weight: int = Field(ge=1)  # spawn weight
    icon: IconCrop | str | None = None

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "hits": self.hits, "value": self.value}


class MineConfig(BaseModel):
    room: str
    per_day: int = Field(ge=1, default=12)
    hit_cooldown_ms: int = Field(ge=0, default=350)
    reach: int = Field(ge=1, default=1)  # Chebyshev distance (cells) from the avatar's foot cell to the node
    pickaxe: IconCrop | str | None = None
    ores: list[Ore] = Field(min_length=1)

    @model_validator(mode="after")
    def _ids(self) -> "MineConfig":
        ids = [o.id for o in self.ores]
        if len(set(ids)) != len(ids):
            raise ValueError("mine.json: duplicate ore id")
        return self

    def ore(self, kind: str) -> Ore | None:
        return next((o for o in self.ores if o.id == kind), None)

    def public(self) -> dict:
        """What GET /api/mine returns (no asset paths)."""
        return {"room": self.room, "per_day": self.per_day, "hit_cooldown_ms": self.hit_cooldown_ms, "reach": self.reach,
                "ores": [o.public() for o in self.ores]}


def load_config(path: Path | None = None) -> MineConfig | None:
    """data/mine.json, or None when there is no mine yet (the routers then answer 404 no_mine)."""
    p = path or (config.DATA_DIR / "mine.json")
    if not p.exists():
        return None
    return MineConfig.model_validate(json.loads(p.read_text(encoding="utf-8")))


# -- days ---------------------------------------------------------------------------------------------------

def day_key(ts: int) -> int:
    """Ordinal of the KST calendar day containing ts (nodes reset at KST midnight)."""
    return datetime.fromtimestamp(ts, KST).date().toordinal()


def next_reset_ts(ts: int) -> int:
    """Unix time of the next KST midnight after ts."""
    local = datetime.fromtimestamp(ts, KST)
    nxt = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(nxt.timestamp())


# -- spawning -----------------------------------------------------------------------------------------------

def _meta(conn: sqlite3.Connection, key: str) -> int:
    row = conn.execute("SELECT v FROM room_meta WHERE k = ?", (key,)).fetchone()
    return int(row[0]) if row else 0


def free_cells(conn: sqlite3.Connection, cat: "Catalog", cfg: MineConfig) -> list[tuple[int, int]]:
    """Floor cells a node may stand on: not blocked, walkable tile, not under any item, not an exit or the spawn."""
    room = cat.rooms[cfg.room]
    taken: set[tuple[int, int]] = set(room.blocked_set)
    taken.add((room.spawn["x"], room.spawn["y"]))
    for e in room.exits:
        for y in range(e.y, e.y + e.h):
            for x in range(e.x, e.x + e.w):
                taken.add((x, y))
    for row in load_items(conn, room.id):
        taken.update(footprint_of(cat, row))
    out = []
    for y in range(room.wall_rows, room.rows):
        for x in range(room.cols):
            if (x, y) not in taken and cat.tile_walkable(room, x, y):
                out.append((x, y))
    return out


def spawn_day(conn: sqlite3.Connection, cat: "Catalog", cfg: MineConfig, ts: int | None = None,
              rng: random.Random | None = None) -> int:
    """Put today's nodes down once (returns how many were spawned; 0 when today is already done).

    Inside the caller's transaction. Yesterday's leftovers are not carried over: only today's rows count.
    """
    ts = ts if ts is not None else now()
    today = day_key(ts)
    key = f"mine_day:{cfg.room}"
    if _meta(conn, key) >= today:
        return 0
    rng = rng or random.Random()
    cells = free_cells(conn, cat, cfg)
    rng.shuffle(cells)
    picked = cells[: cfg.per_day]
    kinds = rng.choices(cfg.ores, weights=[o.weight for o in cfg.ores], k=len(picked))
    conn.executemany(
        "INSERT INTO ore_nodes(day, room_id, x, y, kind, hits_left) VALUES (?, ?, ?, ?, ?, ?)",
        [(today, cfg.room, x, y, o.id, o.hits) for (x, y), o in zip(picked, kinds)],
    )
    conn.execute("INSERT INTO room_meta(k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v", (key, today))
    return len(picked)


def nodes(conn: sqlite3.Connection, cfg: MineConfig, ts: int | None = None) -> dict:
    """Today's standing nodes + how many are left and when the next set comes."""
    ts = ts if ts is not None else now()
    today = day_key(ts)
    rows = conn.execute(
        "SELECT seq, x, y, kind, hits_left FROM ore_nodes WHERE room_id = ? AND day = ? AND mined_by IS NULL ORDER BY seq",
        (cfg.room, today)).fetchall()
    out = []
    for r in rows:
        ore = cfg.ore(r["kind"])
        out.append({"seq": r["seq"], "x": r["x"], "y": r["y"], "kind": r["kind"], "hits_left": r["hits_left"],
                    "hits": ore.hits if ore else r["hits_left"]})
    return {"day": today, "nodes": out, "left": len(out), "per_day": cfg.per_day, "resets_at": next_reset_ts(ts)}


def left_today(conn: sqlite3.Connection, cfg: MineConfig, ts: int | None = None) -> int:
    ts = ts if ts is not None else now()
    return int(conn.execute("SELECT COUNT(*) FROM ore_nodes WHERE room_id = ? AND day = ? AND mined_by IS NULL",
                            (cfg.room, day_key(ts))).fetchone()[0])


# -- mining -------------------------------------------------------------------------------------------------

@dataclass
class Hit:
    seq: int
    x: int
    y: int
    kind: str
    hits_left: int
    done: bool
    ore: Ore
    ledger_seq: int | None = None  # the 'mine' ledger row when the node broke and was worth something


def hit(conn: sqlite3.Connection, cfg: MineConfig, player_id: str, seq: int, ts: int | None = None) -> Hit:
    """One press of 채광 on a node. Inside the caller's transaction; the caller logs the event / advances stages.

    Raises 400 node_gone for a node that does not exist, belongs to another day or is already broken.
    """
    ts = ts if ts is not None else now()
    row = conn.execute("SELECT seq, room_id, day, x, y, kind, hits_left, mined_by FROM ore_nodes WHERE seq = ?",
                       (seq,)).fetchone()
    if row is None or row["room_id"] != cfg.room or row["day"] != day_key(ts) or row["mined_by"] is not None:
        raise ApiError(400, "node_gone")
    ore = cfg.ore(row["kind"])
    if ore is None:  # the config lost this kind since it spawned: nothing to pay, just clear it
        conn.execute("UPDATE ore_nodes SET hits_left = 0, mined_by = ?, mined_ts = ? WHERE seq = ?", (player_id, ts, seq))
        raise ApiError(400, "node_gone")
    left = max(0, int(row["hits_left"]) - 1)
    done = left == 0
    ledger_seq: int | None = None
    if done:
        conn.execute("UPDATE ore_nodes SET hits_left = 0, mined_by = ?, mined_ts = ? WHERE seq = ?", (player_id, ts, seq))
        if ore.value > 0:
            cur = conn.execute(
                "INSERT INTO ledger(ts, player_id, amount, kind, item_uid, item_id) VALUES (?, ?, ?, ?, NULL, ?)",
                (ts, player_id, -ore.value, LEDGER_KIND, f"{LEDGER_KIND}:{ore.id}"),
            )
            ledger_seq = cur.lastrowid
    else:
        conn.execute("UPDATE ore_nodes SET hits_left = ? WHERE seq = ?", (left, seq))
    return Hit(seq=seq, x=row["x"], y=row["y"], kind=ore.id, hits_left=left, done=done, ore=ore, ledger_seq=ledger_seq)


def foot_cell(x: float, y: float) -> tuple[int, int]:
    """The cell an avatar stands on from its presence position (mirrors client Avatar.footCell)."""
    return math.floor(x), math.floor(y - 0.5)


def in_reach(cfg: MineConfig, foot: tuple[int, int], node_xy: tuple[int, int]) -> bool:
    return max(abs(foot[0] - node_xy[0]), abs(foot[1] - node_xy[1])) <= cfg.reach


@dataclass
class Mine:
    """Process-wide mine state: the config plus the per-player hit cooldown (memory only, one worker)."""
    cfg: MineConfig
    last_hit: dict[str, float] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def check_cooldown(self, player_id: str) -> None:
        t = time.monotonic()
        with self.lock:
            if t - self.last_hit.get(player_id, -1e9) < self.cfg.hit_cooldown_ms / 1000:
                raise ApiError(429, "mine_cooldown")
            self.last_hit[player_id] = t
