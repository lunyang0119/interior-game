"""The mine: up to `floors` floors of random rocks, ore nodes and a hidden ladder, fresh every KST calendar day.

data/mine.json names the mine room (a grid room with `kind: "mine"`), how many floors there are, how many nodes a
floor gets, the ore kinds (hits, value, sprite = an interior atlas slice, `wall` for ores embedded in the back
wall) and which ores each tier of floors spawns (`tiers`: weights per floor range). Every floor reuses the room's
geometry (tiles, exits, seeded props); what changes per floor and per day is generated here the first time the
floor is asked for (`ensure_floor`): rock clusters (partition sprites that block walking, `rock_density` of the
free floor cells; whatever the spawn cannot reach is filled with rock too), `nodes_per_floor` ore nodes on cells
the spawn can reach (wall ores on the wall row right above the floor), and one dud node (value 0) that hides the
ladder down — any other floor dud opens it with `ladder_chance` (wall ores never do). Stepping on the open ladder enters the next floor;
room_meta 'mine_deepest:<room>' remembers the deepest floor ever opened so the map entrance can offer it again.

Every node is shared: each `POST /api/mine/hit` takes one off its hits_left and the hit that empties it pays the
shared pool (ledger.kind='mine') in that player's name, like a fish catch — deliverable within the same window.
Nodes never carry over: a new day means new floors, whether or not yesterday's were mined.

Presence rooms are per floor: "<room>#<floor>" (presence.split_room), so you only see people on your floor.
Like fishing.py the config is pure pydantic; the DB side lives here too (generate/view/hit) because it is small.
"""

from __future__ import annotations

import json
import math
import random
import sqlite3
import threading
import time
from collections import deque
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
    from .catalog import Catalog, Room

KST = timezone(timedelta(hours=9))
LEDGER_KIND = "mine"
ROOM_KIND = "mine"  # catalog.Room.kind of the mine room
Cell = tuple[int, int]
STEPS4 = ((1, 0), (-1, 0), (0, 1), (0, -1))


class IconCrop(BaseModel):
    """A cell of a sprite sheet under assets/graphic (build crops it to gen/mine/<id>.png)."""
    file: str
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(ge=1, default=16)
    h: int = Field(ge=1, default=16)


class Ore(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str
    hits: int = Field(ge=1)  # presses of 채광 to break it
    value: int = Field(ge=0)  # money into the pool when it breaks (0 = a dud: rock that may hide the ladder)
    sprite: str | None = None  # interior atlas slice drawn in the room (build also crops it to gen/mine/<id>.png)
    wall: bool = False  # sits in the back wall's bottom row, mined from the floor cell below
    icon: IconCrop | str | None = None  # explicit overlay icon when `sprite` is not the one to show

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "hits": self.hits, "value": self.value, "sprite": self.sprite, "wall": self.wall}


class Tier(BaseModel):
    floors: tuple[int, int]  # inclusive range
    weights: dict[str, int]  # ore id → spawn weight

    @model_validator(mode="after")
    def _range(self) -> "Tier":
        lo, hi = self.floors
        if lo < 1 or hi < lo:
            raise ValueError(f"mine.json: bad tier floors {self.floors}")
        if not self.weights or any(w < 0 for w in self.weights.values()) or sum(self.weights.values()) <= 0:
            raise ValueError(f"mine.json: tier {self.floors} needs positive weights")
        return self


class MineConfig(BaseModel):
    room: str
    floors: int = Field(ge=1, default=20)
    nodes_per_floor: int = Field(ge=1, default=10)
    hit_cooldown_ms: int = Field(ge=0, default=350)
    reach: int = Field(ge=1, default=1)  # Chebyshev distance (cells) from the avatar's foot cell to the node
    rock_density: float = Field(ge=0, le=0.6, default=0.12)  # share of the free floor cells turned into rock clusters
    rocks: list[str] = []  # atlas slices (partition-tagged wall tiles) used for random rocks; empty = no rocks
    ladder: str | None = None  # atlas slice drawn on the open ladder cell (the client draws a hole without it)
    ladder_chance: float = Field(ge=0, le=1, default=0.25)  # a dud that is not *the* ladder node still opens one
    pickaxe: list[str] | IconCrop | str | None = None  # 채광 button frames (atlas slices) or one icon crop
    swing: str | None = None  # atlas slice the client swings down onto the node on every press (none = no swing)
    ores: list[Ore] = Field(min_length=1)
    tiers: list[Tier] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> "MineConfig":
        ids = [o.id for o in self.ores]
        if len(set(ids)) != len(ids):
            raise ValueError("mine.json: duplicate ore id")
        known = set(ids)
        tiers = sorted(self.tiers, key=lambda t: t.floors[0])
        want = 1
        for t in tiers:
            lo, hi = t.floors
            if lo != want:
                raise ValueError(f"mine.json: tiers must cover floors 1..{self.floors} without gaps (floor {want})")
            want = hi + 1
            unknown = set(t.weights) - known
            if unknown:
                raise ValueError(f"mine.json: tier {t.floors} names unknown ore(s) {sorted(unknown)}")
            if not any(self.ore(k).value == 0 and w > 0 for k, w in t.weights.items()):  # type: ignore[union-attr]
                raise ValueError(f"mine.json: tier {t.floors} needs a value-0 ore (it hides the ladder)")
        if want != self.floors + 1:
            raise ValueError(f"mine.json: tiers cover floors 1..{want - 1}, floors is {self.floors}")
        self.tiers = tiers
        return self

    def ore(self, kind: str) -> Ore | None:
        return next((o for o in self.ores if o.id == kind), None)

    def tier_for(self, floor: int) -> Tier:
        return next(t for t in self.tiers if t.floors[0] <= floor <= t.floors[1])

    def presence_room(self, floor: int) -> str:
        return f"{self.room}#{floor}"

    def public(self) -> dict:
        """What GET /api/mine returns (no asset paths; atlas keys are fine, the client needs them)."""
        return {"room": self.room, "floors": self.floors, "nodes_per_floor": self.nodes_per_floor,
                "hit_cooldown_ms": self.hit_cooldown_ms, "reach": self.reach, "ladder": self.ladder,
                "swing": self.swing, "ores": [o.public() for o in self.ores]}


def load_config(path: Path | None = None) -> MineConfig | None:
    """data/mine.json, or None when there is no mine yet (the routers then answer 404 no_mine)."""
    p = path or (config.DATA_DIR / "mine.json")
    if not p.exists():
        return None
    return MineConfig.model_validate(json.loads(p.read_text(encoding="utf-8")))


# -- days ---------------------------------------------------------------------------------------------------

def day_key(ts: int) -> int:
    """Ordinal of the KST calendar day containing ts (floors reset at KST midnight)."""
    return datetime.fromtimestamp(ts, KST).date().toordinal()


def next_reset_ts(ts: int) -> int:
    """Unix time of the next KST midnight after ts."""
    local = datetime.fromtimestamp(ts, KST)
    nxt = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(nxt.timestamp())


# -- meta ---------------------------------------------------------------------------------------------------

def _meta(conn: sqlite3.Connection, key: str, default: int = 0) -> int:
    row = conn.execute("SELECT v FROM room_meta WHERE k = ?", (key,)).fetchone()
    return int(row[0]) if row else default


def _set_meta(conn: sqlite3.Connection, key: str, v: int) -> None:
    conn.execute("INSERT INTO room_meta(k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v", (key, v))


def deepest(conn: sqlite3.Connection, cfg: MineConfig) -> int:
    """The deepest floor anyone has ever opened (the map entrance offers 1..deepest)."""
    return max(1, min(cfg.floors, _meta(conn, f"mine_deepest:{cfg.room}", 1)))


def open_floor(conn: sqlite3.Connection, cfg: MineConfig, floor: int) -> None:
    if floor > _meta(conn, f"mine_deepest:{cfg.room}", 1):
        _set_meta(conn, f"mine_deepest:{cfg.room}", floor)


def ladder_open(conn: sqlite3.Connection, cfg: MineConfig, floor: int, ts: int) -> Cell | None:
    row = conn.execute("SELECT ladder_x, ladder_y FROM mine_floors WHERE room_id = ? AND day = ? AND floor = ?",
                       (cfg.room, day_key(ts), floor)).fetchone()
    if row is None or row["ladder_x"] is None:
        return None
    return int(row["ladder_x"]), int(row["ladder_y"])


def can_enter(conn: sqlite3.Connection, cfg: MineConfig, floor: int, ts: int | None = None) -> bool:
    """A floor is open when someone reached it before, or today's ladder on the floor above is open."""
    ts = ts if ts is not None else now()
    if not 1 <= floor <= cfg.floors:
        return False
    return floor <= deepest(conn, cfg) or ladder_open(conn, cfg, floor - 1, ts) is not None


# -- generation ---------------------------------------------------------------------------------------------

def _taken_by_room(conn: sqlite3.Connection, cat: "Catalog", room: "Room") -> set[Cell]:
    """Cells nothing may spawn on: blocked, the spawn, exits, and every item footprint (seeded props)."""
    taken: set[Cell] = set(room.blocked_set)
    taken.add((room.spawn["x"], room.spawn["y"]))
    for e in room.exits:
        for y in range(e.y, e.y + e.h):
            for x in range(e.x, e.x + e.w):
                taken.add((x, y))
    for row in load_items(conn, room.id):
        taken.update(footprint_of(cat, row))
    return taken


def free_cells(conn: sqlite3.Connection, cat: "Catalog", cfg: MineConfig, rocks: set[Cell] | None = None) -> list[Cell]:
    """Floor cells a node or rock may stand on: not blocked, walkable tile, not under any item, not an exit or the spawn."""
    room = cat.rooms[cfg.room]
    taken = _taken_by_room(conn, cat, room)
    if rocks:
        taken |= rocks
    return [(x, y) for y in range(room.wall_rows, room.rows) for x in range(room.cols)
            if (x, y) not in taken and cat.tile_walkable(room, x, y)]


def _reachable(cat: "Catalog", room: "Room", rocks: set[Cell]) -> set[Cell]:
    """Floor cells the spawn can walk to (4 directions; rocks, blocked cells and walk:false tiles stop it).
    Items do not count: seeded props never block walking in the client either."""
    blocked = set(room.blocked_set) | rocks

    def ok(c: Cell) -> bool:
        x, y = c
        return room.wall_rows <= y < room.rows and 0 <= x < room.cols and c not in blocked and cat.tile_walkable(room, x, y)

    start: Cell = (room.spawn["x"], room.spawn["y"])
    seen = {start}
    q = deque([start])
    while q:
        x, y = q.popleft()
        for dx, dy in STEPS4:
            n = (x + dx, y + dy)
            if n not in seen and ok(n):
                seen.add(n)
                q.append(n)
    return seen


def _near(cells: set[Cell], room: "Room") -> set[Cell]:
    """The cells plus their 8 neighbours (kept clear of rocks around the spawn and exits)."""
    out = set()
    for x, y in cells:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                out.add((x + dx, y + dy))
    return out


def layout_floor(conn: sqlite3.Connection, cat: "Catalog", cfg: MineConfig, floor: int, rng: random.Random
                 ) -> tuple[dict[Cell, str], list[tuple[Cell, Ore, bool]]]:
    """Pure part of a floor: rocks {cell: key} and nodes [(cell, ore, hides_ladder)]."""
    room = cat.rooms[cfg.room]
    free = free_cells(conn, cat, cfg)
    free_set = set(free)
    protected = _near({(room.spawn["x"], room.spawn["y"])} | {(x, y) for e in room.exits for y in range(e.y, e.y + e.h)
                                                                for x in range(e.x, e.x + e.w)}, room)
    rocks: dict[Cell, str] = {}
    if cfg.rocks and cfg.rock_density > 0 and free:
        target = round(len(free) * cfg.rock_density)
        tries = 0
        while len(rocks) < target and tries < target * 20 + 20:
            tries += 1
            cur = rng.choice(free)
            for _ in range(rng.randint(2, 4)):  # a short random walk makes a cluster
                if cur in free_set and cur not in rocks and cur not in protected:
                    rocks[cur] = rng.choice(cfg.rocks)
                dx, dy = rng.choice(STEPS4)
                cur = (cur[0] + dx, cur[1] + dy)
        reach = _reachable(cat, room, set(rocks))
        for c in free:  # pockets the spawn cannot reach become solid rock
            if c not in reach and c not in rocks:
                rocks[c] = rng.choice(cfg.rocks)
    reach = _reachable(cat, room, set(rocks))
    taken = _taken_by_room(conn, cat, room)
    floor_cells = [c for c in free if c in reach and c not in rocks]
    wall_cells: list[Cell] = []
    if room.wall_rows > 0:
        wy = room.wall_rows - 1
        wall_cells = [(x, wy) for x in range(1, room.cols - 1)
                      if (x, wy) not in taken and (x, wy + 1) in reach and (x, wy + 1) not in rocks]
    rng.shuffle(floor_cells)
    rng.shuffle(wall_cells)
    tier = cfg.tier_for(floor)
    ids = [k for k, w in tier.weights.items() if w > 0]
    weights = [tier.weights[k] for k in ids]
    fallback = next((cfg.ore(k) for k in ids if not cfg.ore(k).wall), None)  # type: ignore[union-attr]
    nodes: list[tuple[Cell, Ore, bool]] = []
    for _ in range(cfg.nodes_per_floor):
        ore = cfg.ore(rng.choices(ids, weights=weights)[0])
        assert ore is not None
        if ore.wall and not wall_cells:
            if fallback is None or not floor_cells:
                continue
            ore = fallback
        pool = wall_cells if ore.wall else floor_cells
        if not pool:
            continue
        nodes.append((pool.pop(), ore, False))
    if floor < cfg.floors:
        duds = [i for i, (_, o, _) in enumerate(nodes) if o.value == 0 and not o.wall]  # wall ores never hide the ladder
        if duds:
            i = rng.choice(duds)
            nodes[i] = (nodes[i][0], nodes[i][1], True)
        else:
            stone = next((cfg.ore(k) for k in ids if cfg.ore(k).value == 0 and not cfg.ore(k).wall), None)  # type: ignore[union-attr]
            stone = stone or next((o for o in cfg.ores if o.value == 0 and not o.wall), None)
            if stone is not None and floor_cells:
                nodes.append((floor_cells.pop(), stone, True))
    return rocks, nodes


def ensure_floor(conn: sqlite3.Connection, cat: "Catalog", cfg: MineConfig, floor: int, ts: int | None = None,
                 rng: random.Random | None = None) -> bool:
    """Generate today's layout of `floor` once (True when it was generated now). Inside the caller's transaction."""
    ts = ts if ts is not None else now()
    today = day_key(ts)
    if conn.execute("SELECT 1 FROM mine_floors WHERE room_id = ? AND day = ? AND floor = ?", (cfg.room, today, floor)).fetchone():
        return False
    rocks, nodes = layout_floor(conn, cat, cfg, floor, rng or random.Random())
    conn.executemany(
        "INSERT INTO ore_nodes(day, room_id, floor, x, y, kind, hits_left, ladder) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(today, cfg.room, floor, x, y, o.id, o.hits, int(ladder)) for (x, y), o, ladder in nodes],
    )
    conn.execute("INSERT INTO mine_floors(room_id, day, floor, rocks) VALUES (?, ?, ?, ?)",
                 (cfg.room, today, floor, json.dumps([[x, y, k] for (x, y), k in sorted(rocks.items())])))
    return True


def floor_view(conn: sqlite3.Connection, cfg: MineConfig, floor: int, ts: int | None = None) -> dict:
    """Today's picture of one floor: rocks, standing nodes, the ladder (once open), how many are left."""
    ts = ts if ts is not None else now()
    today = day_key(ts)
    row = conn.execute("SELECT rocks, ladder_x, ladder_y FROM mine_floors WHERE room_id = ? AND day = ? AND floor = ?",
                       (cfg.room, today, floor)).fetchone()
    rocks = json.loads(row["rocks"]) if row else []
    ladder = {"x": row["ladder_x"], "y": row["ladder_y"]} if row and row["ladder_x"] is not None else None
    rows = conn.execute(
        "SELECT seq, x, y, kind, hits_left FROM ore_nodes WHERE room_id = ? AND day = ? AND floor = ? AND mined_by IS NULL ORDER BY seq",
        (cfg.room, today, floor)).fetchall()
    out = []
    for r in rows:
        ore = cfg.ore(r["kind"])
        out.append({"seq": r["seq"], "x": r["x"], "y": r["y"], "kind": r["kind"], "hits_left": r["hits_left"],
                    "hits": ore.hits if ore else r["hits_left"], "wall": bool(ore and ore.wall)})
    return {"day": today, "floor": floor, "floors": cfg.floors, "deepest": deepest(conn, cfg), "rocks": rocks, "ladder": ladder,
            "nodes": out, "left": len(out), "per_floor": cfg.nodes_per_floor, "resets_at": next_reset_ts(ts)}


def left_on(conn: sqlite3.Connection, cfg: MineConfig, floor: int, ts: int | None = None) -> int:
    ts = ts if ts is not None else now()
    return int(conn.execute("SELECT COUNT(*) FROM ore_nodes WHERE room_id = ? AND day = ? AND floor = ? AND mined_by IS NULL",
                            (cfg.room, day_key(ts), floor)).fetchone()[0])


# -- mining -------------------------------------------------------------------------------------------------

@dataclass
class Hit:
    seq: int
    floor: int
    x: int
    y: int
    kind: str
    hits_left: int
    done: bool
    ore: Ore
    ledger_seq: int | None = None  # the 'mine' ledger row when the node broke and was worth something
    ladder: Cell | None = None  # the ladder this hit uncovered (floor cell), if any


def node_floor(conn: sqlite3.Connection, seq: int) -> tuple[int, int, int] | None:
    """(floor, x, y) of a node, or None."""
    row = conn.execute("SELECT floor, x, y FROM ore_nodes WHERE seq = ?", (seq,)).fetchone()
    return (int(row["floor"]), int(row["x"]), int(row["y"])) if row else None


def hit(conn: sqlite3.Connection, cfg: MineConfig, player_id: str, seq: int, ts: int | None = None,
        rng: random.Random | None = None) -> Hit:
    """One press of 채광 on a node. Inside the caller's transaction; the caller logs the event / advances stages.

    Raises 400 node_gone for a node that does not exist, belongs to another day or is already broken.
    """
    ts = ts if ts is not None else now()
    row = conn.execute("SELECT seq, room_id, day, floor, x, y, kind, hits_left, mined_by, ladder FROM ore_nodes WHERE seq = ?",
                       (seq,)).fetchone()
    if row is None or row["room_id"] != cfg.room or row["day"] != day_key(ts) or row["mined_by"] is not None:
        raise ApiError(400, "node_gone")
    ore = cfg.ore(row["kind"])
    if ore is None:  # the config lost this kind since it spawned: nothing to pay, just clear it
        conn.execute("UPDATE ore_nodes SET hits_left = 0, mined_by = ?, mined_ts = ? WHERE seq = ?", (player_id, ts, seq))
        raise ApiError(400, "node_gone")
    floor = int(row["floor"])
    left = max(0, int(row["hits_left"]) - 1)
    done = left == 0
    ledger_seq: int | None = None
    ladder: Cell | None = None
    if done:
        conn.execute("UPDATE ore_nodes SET hits_left = 0, mined_by = ?, mined_ts = ? WHERE seq = ?", (player_id, ts, seq))
        if ore.value > 0:
            cur = conn.execute(
                "INSERT INTO ledger(ts, player_id, amount, kind, item_uid, item_id) VALUES (?, ?, ?, ?, NULL, ?)",
                (ts, player_id, -ore.value, LEDGER_KIND, f"{LEDGER_KIND}:{ore.id}"),
            )
            ledger_seq = cur.lastrowid
        elif not ore.wall and floor < cfg.floors and ladder_open(conn, cfg, floor, ts) is None:
            rng = rng or random.Random()
            if row["ladder"] or rng.random() < cfg.ladder_chance:
                ladder = (int(row["x"]), int(row["y"]))
                conn.execute("UPDATE mine_floors SET ladder_x = ?, ladder_y = ? WHERE room_id = ? AND day = ? AND floor = ?",
                             (ladder[0], ladder[1], cfg.room, row["day"], floor))
    else:
        conn.execute("UPDATE ore_nodes SET hits_left = ? WHERE seq = ?", (left, seq))
    return Hit(seq=seq, floor=floor, x=row["x"], y=row["y"], kind=ore.id, hits_left=left, done=done, ore=ore,
               ledger_seq=ledger_seq, ladder=ladder)


def foot_cell(x: float, y: float) -> Cell:
    """The cell an avatar stands on from its presence position (mirrors client Avatar.footCell)."""
    return math.floor(x), math.floor(y - 0.5)


def in_reach(cfg: MineConfig, foot: Cell, node_xy: Cell) -> bool:
    return max(abs(foot[0] - node_xy[0]), abs(foot[1] - node_xy[1])) <= cfg.reach


@dataclass
class Mine:
    """Process-wide mine state: the config plus the per-player hit cooldown (memory only, one worker)."""
    cfg: MineConfig
    last_hit: dict[str, float] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)
    last_day: int = 0  # KST day the minute tick last saw (main.spawn_mine broadcasts `mine_reset` when it changes)

    def check_cooldown(self, player_id: str) -> None:
        t = time.monotonic()
        with self.lock:
            if t - self.last_hit.get(player_id, -1e9) < self.cfg.hit_cooldown_ms / 1000:
                raise ApiError(429, "mine_cooldown")
            self.last_hit[player_id] = t
