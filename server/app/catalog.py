"""Loads and validates data/items.json, data/room.json and gen/manifest.json."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from . import config

Layer = Literal["wall", "floor", "furniture", "surface_item"]
Z_OF_LAYER: dict[str, int] = {"wall": 0, "floor": 0, "furniture": 1, "surface_item": 2}


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

    @model_validator(mode="after")
    def _rules(self) -> "Item":
        if self.is_surface and self.layer != "furniture":
            raise ValueError(f"{self.id}: only furniture can be is_surface")
        if self.layer == "surface_item" and self.w * self.h > 2:
            raise ValueError(f"{self.id}: surface_item footprint must be <= 2 cells")
        return self


class RoomTiles(BaseModel):
    wall: list[str]
    wall_left: list[str] = []
    wall_right: list[str] = []
    floor: str


class Room(BaseModel):
    cols: int = Field(ge=4)
    rows: int = Field(ge=4)
    wall_rows: int = Field(ge=0)
    spawn: dict[str, int]
    blocked: list[list[int]] = []
    zoom: int = 2
    tiles: RoomTiles

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
    room: Room
    manifest: dict
    layer_counts: dict[str, int] = field(default_factory=dict)

    def get(self, item_id: str) -> Item | None:
        return self.items.get(item_id)

    def public(self) -> dict:
        """What GET /api/catalog returns."""
        return {
            "items": [it.model_dump() for it in self.items.values()],
            "room": self.room.model_dump(),
            "chars": self.manifest["chars"],
        }


def load(data_dir: Path | None = None, gen_dir: Path | None = None) -> Catalog:
    data_dir = data_dir or config.DATA_DIR
    gen_dir = gen_dir or config.GEN_DIR

    raw_items = json.loads((data_dir / "items.json").read_text(encoding="utf-8"))["items"]
    room = Room.model_validate(json.loads((data_dir / "room.json").read_text(encoding="utf-8")))
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

    tiles = room.tiles
    for key in [*tiles.wall, *tiles.wall_left, *tiles.wall_right, tiles.floor]:
        if key not in keys:
            raise ValueError(f"room tile '{key}' not in manifest")
    if len(tiles.wall) != room.wall_rows:
        raise ValueError("room.tiles.wall must have one key per wall row")

    layer_counts = {name: spec["count"] for name, spec in manifest["chars"]["layers"].items()}
    return Catalog(items=items, room=room, manifest=manifest, layer_counts=layer_counts)
