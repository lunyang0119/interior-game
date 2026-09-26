"""Loads and validates data/items.json, data/rooms/*.json and gen/manifest.json."""

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
DEFAULT_ROOM = "inn"
MAP_ROOM = "map"


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
    tags: list[str] = []
    pair: str | None = None  # the intact/ruined counterpart (informational)

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
    exits: list[Exit] = []
    seed: list[Seed] = []

    @property
    def blocked_set(self) -> set[tuple[int, int]]:
        return {(b[0], b[1]) for b in self.blocked}

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.cols and 0 <= y < self.rows

    def cell_type(self, x: int, y: int) -> str:
        return "wall" if y < self.wall_rows else "floor"


@dataclass
class Catalog:
    items: dict[str, Item]
    rooms: dict[str, Room]
    manifest: dict
    layer_counts: dict[str, int] = field(default_factory=dict)
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

    def public(self) -> dict:
        """What GET /api/catalog returns. Static for the process lifetime, so it is built once."""
        if self._public is None:
            self._public = {
                "items": [it.model_dump() for it in self.items.values()],
                "room": self.room.model_dump(),
                "rooms": [r.model_dump() for r in self.rooms.values()],
                "chars": self.manifest["chars"],
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

    layer_counts = {name: spec["count"] for name, spec in manifest["chars"]["layers"].items()}
    return Catalog(items=items, rooms=rooms, manifest=manifest, layer_counts=layer_counts)
