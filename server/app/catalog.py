"""Loads and validates data/items.json, data/rooms/*.json, data/map.json and gen/manifest.json."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from . import config
from .restore import Stage, validate_restore

log = logging.getLogger("catalog")

Layer = Literal["wallpaper", "wall", "floor", "furniture", "surface_item"]
# wall > wallpaper so a tap on a frame hung over wallpaper picks the frame
Z_OF_LAYER: dict[str, int] = {"wallpaper": 0, "wall": 1, "floor": 0, "furniture": 1, "surface_item": 2}
WALL_LAYERS = ("wallpaper", "wall")

TAG_RE = re.compile(r"^[a-z0-9_]+$")
ROOM_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
# tags with rules: ruined = seeded junk that can only be sold; fixed = part of the room (no buy/move/sell)
TAG_RUINED = "ruined"
TAG_FIXED = "fixed"
TAG_NOTE = "note"  # carries a short text anyone can rewrite (PUT /api/room/item/{uid}/note)
# partition = a wall-layer sprite that stands on the floor (room dividers): placed on floor rows, collides and
# blocks walking like furniture, drawn like furniture. door = a partition avatars may walk through.
TAG_PARTITION = "partition"
TAG_DOOR = "door"
DEFAULT_ROOM = "inn"
MAP_ROOM = "map"
DOCK_ROOM = "dock"
# Tile metadata set on slices in the editor and carried in gen/manifest.json keys:
# step = footstep sound kind, walk = False → avatars cannot enter (and furniture/rugs cannot be placed there).
TILE_STEPS = ("wood", "tile", "grass", "water", "none")


class Item(BaseModel):
    id: str
    name: str
    price: int = Field(ge=0)
    sprite: str
    w: int = Field(ge=1)
    h: int = Field(ge=1)
    layer: Layer
    is_surface: bool = False
    surface_offset_y: int = 0
    # draw the sprite this many px lower than its footprint anchor (an open door hanging below a wall's base);
    # purely visual, the footprint does not move
    offset_y: int = 0
    tags: list[str] = []
    pair: str | None = None  # the intact/ruined counterpart (informational)
    # furniture set (same source pack/theme) — not in items.json: filled from the manifest key's `set` at load,
    # which `build` derives from the slice source. Used by the comfort score's set bonus.
    set: str | None = None

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        for t in v:
            if not TAG_RE.match(t):
                raise ValueError(f"bad tag '{t}'")
        return sorted(set(v))

    @model_validator(mode="after")
    def _rules(self) -> "Item":
        if self.is_surface and self.layer != "furniture":
            raise ValueError(f"{self.id}: only furniture can be is_surface")
        return self

    def has_tag(self, tag: str) -> bool:
        return tag in self.tags

    @property
    def on_wall(self) -> bool:
        """Lives on the wall rows (wallpaper / wall decor), unless it is a partition standing on the floor."""
        return self.layer in WALL_LAYERS and not self.has_tag(TAG_PARTITION)

    @property
    def collision_layer(self) -> str:
        """Items only collide within this group; partitions share the floor with furniture."""
        return "furniture" if self.has_tag(TAG_PARTITION) else self.layer

    @property
    def for_sale(self) -> bool:
        return not (self.has_tag(TAG_RUINED) or self.has_tag(TAG_FIXED))


class RoomTiles(BaseModel):
    wall: list[str]
    wall_left: list[str] = []
    wall_right: list[str] = []
    floor: str


class Exit(BaseModel):
    """Cells that lead somewhere else. `to` is a room id or "map"; `spawn` is where you appear there."""
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(ge=1)
    h: int = Field(ge=1)
    to: str
    spawn: dict[str, int] = {"x": 0, "y": 0}

    def contains(self, x: int, y: int) -> bool:
        return self.x <= x < self.x + self.w and self.y <= y < self.y + self.h


class Seed(BaseModel):
    """An item placed once by the system when the room is first seen (owner: config.SEED_PLAYER)."""
    item_id: str
    x: int
    y: int
    span: int | None = Field(default=None, ge=1)


class Zone(BaseModel):
    """A rectangle inside a room that takes guests on its own (a guest room on a floor). Drawn in the world
    editor ("구역 그리기"). Rooms without zones are one guest unit as a whole."""
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str = ""
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(ge=1)
    h: int = Field(ge=1)

    def contains(self, x: int, y: int) -> bool:
        return self.x <= x < self.x + self.w and self.y <= y < self.y + self.h

    @property
    def cells(self) -> int:
        return self.w * self.h


class Room(BaseModel):
    id: str = DEFAULT_ROOM
    name: str = ""
    cols: int = Field(ge=4)
    rows: int = Field(ge=4)
    wall_rows: int = Field(ge=0)
    spawn: dict[str, int]
    blocked: list[list[int]] = []
    zoom: int = 2
    tiles: RoomTiles
    # Optional per-cell floor tiles (rows × cols, painted in the world editor). None = tiles.floor.
    floor: list[list[str | None]] | None = None
    exits: list[Exit] = []
    seed: list[Seed] = []
    # Restoration stages (needs → unlock rewards), see restore.py. Empty = the room has no progression.
    restore: list[Stage] = []
    # Guest rooms inside this room (comfort/guests per zone). Empty = the whole room is one guest unit.
    zones: list[Zone] = []

    @model_validator(mode="after")
    def _zones(self) -> "Room":
        seen: set[str] = set()
        for z in self.zones:
            if z.id in seen:
                raise ValueError(f"room {self.id}: duplicate zone id '{z.id}'")
            seen.add(z.id)
            if z.x + z.w > self.cols or z.y + z.h > self.rows:
                raise ValueError(f"room {self.id}: zone '{z.id}' sticks out of the room")
        for i, a in enumerate(self.zones):
            for b in self.zones[i + 1:]:
                if a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h:
                    raise ValueError(f"room {self.id}: zones '{a.id}' and '{b.id}' overlap")
        return self

    def zone_at(self, x: int, y: int) -> "Zone | None":
        return next((z for z in self.zones if z.contains(x, y)), None)

    @property
    def cells(self) -> int:
        return self.cols * self.rows

    def floor_key(self, x: int, y: int) -> str:
        """The floor tile drawn at a cell (wall rows still answer with the default floor)."""
        if self.floor is not None and 0 <= y < len(self.floor) and 0 <= x < len(self.floor[y]):
            return self.floor[y][x] or self.tiles.floor
        return self.tiles.floor

    @property
    def blocked_set(self) -> set[tuple[int, int]]:
        return {(b[0], b[1]) for b in self.blocked}

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.cols and 0 <= y < self.rows

    def cell_type(self, x: int, y: int) -> str:
        return "wall" if y < self.wall_rows else "floor"


class MapPlace(BaseModel):
    """A house/dock on the overworld. Standing on a door cell asks to enter `room` (a room id or "dock")."""
    room: str
    name: str = ""
    sprite: str | None = None
    x: int
    y: int
    w: int = Field(ge=1, default=1)
    h: int = Field(ge=1, default=1)
    rot: int = 0
    flip: bool = False
    doors: list[list[int]] = []
    spawn: dict[str, int] | None = None  # where you stand on the map after leaving this place


class MapDeco(BaseModel):
    sprite: str
    x: int
    y: int
    rot: int = 0
    flip: bool = False


class BgZone(BaseModel):
    """Cells where the fixed (non-scrolling) backdrop `bg` shows; later zones win when they overlap."""
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(ge=1)
    h: int = Field(ge=1)
    bg: str


class MapData(BaseModel):
    cols: int = Field(ge=4)
    rows: int = Field(ge=4)
    spawn: dict[str, int]
    layers: dict[str, list[list[str | None]]] = {}
    blocked: list[list[int]] = []
    places: list[MapPlace] = []
    decos: list[MapDeco] = []
    bg_default: str | None = None  # gen/mapbg/<name>.png shown where no zone applies (None = plain colour)
    bg_zones: list[BgZone] = []


class TileMeta(BaseModel):
    step: Literal["wood", "tile", "grass", "water", "none"] | None = None
    walk: bool = True


@dataclass
class Catalog:
    items: dict[str, Item]
    rooms: dict[str, Room]
    manifest: dict
    map: MapData | None = None
    layer_counts: dict[str, int] = field(default_factory=dict)
    # {"interior": {key: TileMeta}, "map": {key: TileMeta}} — only keys that carry step/walk
    tiles: dict[str, dict[str, TileMeta]] = field(default_factory=lambda: {"interior": {}, "map": {}})
    # hash of the generated atlases + theme: the client appends it to /gen and /media URLs so a rebuild
    # bypasses the long browser/Caddy cache instead of serving a stale atlas for a day
    asset_version: str = ""
    _public: dict | None = field(default=None, repr=False)
    _etag: str = field(default="", repr=False)

    @property
    def room(self) -> Room:
        """The base room (inn): where a new connection starts and what the old single-room API means."""
        return self.rooms.get(DEFAULT_ROOM) or next(iter(self.rooms.values()))

    def get(self, item_id: str) -> Item | None:
        return self.items.get(item_id)

    def room_of(self, room_id: str) -> Room | None:
        return self.rooms.get(room_id)

    def tile_walkable(self, room: Room, x: int, y: int) -> bool:
        meta = self.tiles["interior"].get(room.floor_key(x, y))
        return meta.walk if meta else True

    def public(self) -> dict:
        """What GET /api/catalog returns. Static for the process lifetime, so it is built once."""
        if self._public is None:
            self._public = {
                "items": [it.model_dump() for it in self.items.values()],
                "room": self.room.model_dump(),
                "rooms": [r.model_dump() for r in self.rooms.values()],
                "map": self.map.model_dump() if self.map else None,
                "chars": self.manifest["chars"],
                # the inn cat's sprite strip (build writes it when the variant PNG exists); None = no cat
                "cat": self.manifest.get("cat"),
                "tiles": {atlas: {k: m.model_dump(exclude_none=True) for k, m in metas.items()}
                          for atlas, metas in self.tiles.items()},
                "asset_version": self.asset_version,
            }
        return self._public

    def etag(self) -> str:
        if not self._etag:
            digest = hashlib.sha1(json.dumps(self.public(), sort_keys=True).encode()).hexdigest()[:16]
            self._etag = '"' + digest + '"'
        return self._etag


def _load_rooms(data_dir: Path) -> dict[str, Room]:
    """data/rooms/<id>.json (file name = id). Falls back to the legacy single data/room.json as 'inn'."""
    rooms: dict[str, Room] = {}
    rooms_dir = data_dir / "rooms"
    if rooms_dir.is_dir():
        for p in sorted(rooms_dir.glob("*.json")):
            raw = json.loads(p.read_text(encoding="utf-8"))
            raw.setdefault("id", p.stem)
            if raw["id"] != p.stem:
                raise ValueError(f"rooms/{p.name}: id '{raw['id']}' must equal the file name")
            if not ROOM_ID_RE.match(p.stem):
                raise ValueError(f"rooms/{p.name}: bad room id")
            rooms[p.stem] = Room.model_validate(raw)
    if not rooms:
        legacy = data_dir / "room.json"
        if not legacy.exists():
            raise ValueError("no rooms: need data/rooms/<id>.json or data/room.json")
        rooms[DEFAULT_ROOM] = Room.model_validate({"id": DEFAULT_ROOM, **json.loads(legacy.read_text(encoding="utf-8"))})
    if DEFAULT_ROOM not in rooms:
        raise ValueError(f"room '{DEFAULT_ROOM}' is required (players start there)")
    return rooms


def asset_version(gen_dir: Path, media_dir: Path | None = None) -> str:
    """Short hash of the files whose layout the client caches (atlas frames, theme, BGM/SFX lists). Missing files
    are skipped. Caddy caches /gen and /media for a day, so anything the client fetches from there must be in
    this hash (and the server restarted after uploading it) or browsers keep the old copy."""
    media = media_dir or config.MEDIA_DIR
    h = hashlib.sha1()
    for p in (gen_dir / "manifest.json", gen_dir / "interiors.json", gen_dir / "map.json", gen_dir / "dock.json",
              media / "theme.css", media / "bgm.json", media / "sfx.json"):
        if p.is_file():
            h.update(p.name.encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:12]


def load(data_dir: Path | None = None, gen_dir: Path | None = None) -> Catalog:
    data_dir = data_dir or config.DATA_DIR
    gen_dir = gen_dir or config.GEN_DIR

    raw_items = json.loads((data_dir / "items.json").read_text(encoding="utf-8"))["items"]
    rooms = _load_rooms(data_dir)
    manifest = json.loads((gen_dir / "manifest.json").read_text(encoding="utf-8"))

    items: dict[str, Item] = {}
    keys = manifest["interiors"]["keys"]
    for raw in raw_items:
        it = Item.model_validate(raw)
        if it.id in items:
            raise ValueError(f"duplicate item id {it.id}")
        if it.sprite not in keys:
            raise ValueError(f"{it.id}: sprite '{it.sprite}' not in manifest")
        spec = keys[it.sprite]
        if isinstance(spec, dict) and spec.get("set"):
            it.set = str(spec["set"])
        items[it.id] = it
    for it in items.values():
        if it.pair is not None and it.pair not in items:
            raise ValueError(f"{it.id}: pair '{it.pair}' is not an item")

    for room in rooms.values():
        tiles = room.tiles
        for key in [*tiles.wall, *tiles.wall_left, *tiles.wall_right, tiles.floor]:
            if key not in keys:
                raise ValueError(f"room {room.id}: tile '{key}' not in manifest")
        if len(tiles.wall) != room.wall_rows:
            raise ValueError(f"room {room.id}: tiles.wall must have one key per wall row")
        if room.floor is not None:
            if len(room.floor) != room.rows or any(len(r) != room.cols for r in room.floor):
                raise ValueError(f"room {room.id}: floor grid is not {room.cols}x{room.rows}")
            for r in room.floor:
                for k in r:
                    if k is not None and k not in keys:
                        raise ValueError(f"room {room.id}: floor tile '{k}' not in manifest")
        if not room.in_bounds(room.spawn["x"], room.spawn["y"]):
            raise ValueError(f"room {room.id}: spawn outside the room")
        for e in room.exits:
            if e.to != MAP_ROOM and e.to not in rooms:
                raise ValueError(f"room {room.id}: exit to unknown room '{e.to}'")
            if not (room.in_bounds(e.x, e.y) and room.in_bounds(e.x + e.w - 1, e.y + e.h - 1)):
                raise ValueError(f"room {room.id}: exit to '{e.to}' is outside the room")
            if e.to in rooms and not rooms[e.to].in_bounds(e.spawn.get("x", -1), e.spawn.get("y", -1)):
                raise ValueError(f"room {room.id}: exit to '{e.to}' spawns outside that room")
        for sd in room.seed:
            if sd.item_id not in items:
                raise ValueError(f"room {room.id}: seed item '{sd.item_id}' is not an item")
        if len({st.id for st in room.restore}) != len(room.restore):
            raise ValueError(f"room {room.id}: duplicate restore stage id")
        for st in room.restore:
            for n in st.need:
                if n.type == "placed" and n.item_id is not None and n.item_id not in items:
                    raise ValueError(f"room {room.id}: stage '{st.id}' needs unknown item '{n.item_id}'")
    validate_restore(rooms, config.SCENE_ROOMS, DEFAULT_ROOM)

    layer_counts = {name: spec["count"] for name, spec in manifest["chars"]["layers"].items()}
    tiles = {"interior": _tile_meta(keys), "map": _tile_meta(manifest.get("map", {}).get("keys", {}))}
    return Catalog(items=items, rooms=rooms, manifest=manifest, layer_counts=layer_counts,
                   map=_load_map(data_dir, rooms, manifest), tiles=tiles, asset_version=asset_version(gen_dir))


def _tile_meta(keys: dict) -> dict[str, TileMeta]:
    """step/walk carried on manifest keys (set per slice in the editor, copied by `build`)."""
    out: dict[str, TileMeta] = {}
    for k, spec in keys.items():
        if not isinstance(spec, dict) or not ({"step", "walk"} & set(spec)):
            continue
        try:
            out[k] = TileMeta.model_validate({f: spec[f] for f in ("step", "walk") if f in spec})
        except ValueError as e:
            raise ValueError(f"manifest key '{k}': bad tile metadata: {e}") from None
    return out


def _load_map(data_dir: Path, rooms: dict[str, Room], manifest: dict) -> MapData | None:
    """data/map.json (written by the world editor). Optional: without it the game has no overworld."""
    p = data_dir / "map.json"
    if not p.exists():
        return None
    m = MapData.model_validate(json.loads(p.read_text(encoding="utf-8")))
    map_keys = set(manifest.get("map", {}).get("keys", {}))
    for name, grid in m.layers.items():
        if len(grid) != m.rows or any(len(r) != m.cols for r in grid):
            raise ValueError(f"map: layers.{name} is not {m.cols}x{m.rows}")
        for r in grid:
            for k in r:
                if k is not None and k not in map_keys:
                    raise ValueError(f"map: tile '{k}' not in the map atlas (build?)")
    if not (0 <= m.spawn.get("x", -1) < m.cols and 0 <= m.spawn.get("y", -1) < m.rows):
        raise ValueError("map: spawn outside the map")
    for pl in m.places:
        if pl.room != DOCK_ROOM and pl.room not in rooms:
            raise ValueError(f"map: place '{pl.name}' leads to unknown room '{pl.room}'")
        if pl.sprite and pl.sprite not in map_keys:
            raise ValueError(f"map: place '{pl.name}' sprite '{pl.sprite}' not in the map atlas")
        if pl.rot not in (0, 90, 180, 270):
            raise ValueError(f"map: place '{pl.name}' rot must be 0/90/180/270")
        for d in pl.doors:
            if len(d) != 2 or not (0 <= d[0] < m.cols and 0 <= d[1] < m.rows):
                raise ValueError(f"map: place '{pl.name}' has a door outside the map")
    for d in m.decos:
        if d.sprite not in map_keys:
            raise ValueError(f"map: deco sprite '{d.sprite}' not in the map atlas")
    bgs = set(manifest.get("mapbg", {}).get("names", []))
    for name in [m.bg_default, *(z.bg for z in m.bg_zones)]:
        if name is not None and name not in bgs:
            raise ValueError(f"map: background '{name}' is not built (gen/mapbg; put the PNG in assets/graphic/Map/Backgrounds and build)")
    return m
