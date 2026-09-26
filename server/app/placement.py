"""Pure placement rules. No DB access here so it is trivial to unit test.

Rules (see plan §3):
1. item exists, footprint inside the room, no blocked cells
2. every footprint cell has the right type for the layer (wallpaper/wall ↔ wall rows, else floor)
3. wallpaper/wall/floor/furniture only collide with items of the same layer
   (so frames, doors and chalkboards can hang over wallpaper)
4. surface_item needs exactly one is_surface furniture under every cell, the same
   one for all cells, and no other surface_item in those cells

`others` must be the rows of the same room; the caller filters by room_id.
"""

from __future__ import annotations

from dataclasses import dataclass

from .catalog import DEFAULT_ROOM, Catalog, Item, WALL_LAYERS, Z_OF_LAYER
from .errors import ApiError


@dataclass(frozen=True)
class ItemRow:
    uid: int
    item_id: str
    x: int
    y: int
    z: int
    parent_uid: int | None
    placed_by: str
    ts: int
    span: int | None = None  # wallpaper only: width in cells chosen at placement
    room_id: str = DEFAULT_ROOM


@dataclass(frozen=True)
class Placement:
    z: int
    parent_uid: int | None


Cell = tuple[int, int]


def fail(code: str) -> ApiError:
    return ApiError(400, code)


def footprint(x: int, y: int, w: int, h: int) -> list[Cell]:
    return [(cx, cy) for cy in range(y, y + h) for cx in range(x, x + w)]


def width_of(it: Item, span: int | None) -> int:
    return span if (it.layer == "wallpaper" and span) else it.w


def price_of(it: Item, span: int | None) -> int:
    """Wallpaper is priced per column; everything else per item."""
    return it.price * width_of(it, span) if it.layer == "wallpaper" else it.price


def footprint_of(catalog: Catalog, row: ItemRow) -> list[Cell]:
    it = catalog.items[row.item_id]
    return footprint(row.x, row.y, width_of(it, row.span), it.h)


def validate_place(catalog: Catalog, others: list[ItemRow], item_id: str, x: int, y: int,
                   span: int | None = None, room_id: str | None = None) -> Placement:
    it: Item | None = catalog.get(item_id)
    if it is None:
        raise fail("unknown_item")
    room = catalog.room if room_id is None else catalog.room_of(room_id)
    if room is None:
        raise ApiError(404, "unknown_room")
    if span is not None and (it.layer != "wallpaper" or not 1 <= span <= room.cols):
        raise fail("bad_span")
    cells = footprint(x, y, width_of(it, span), it.h)
    blocked = room.blocked_set
    if any(not room.in_bounds(cx, cy) or (cx, cy) in blocked for cx, cy in cells):
        raise fail("out_of_bounds")

    want = "wall" if it.layer in WALL_LAYERS else "floor"
    if any(room.cell_type(cx, cy) != want for cx, cy in cells):
        raise fail("bad_cell_type")

    cell_set = set(cells)

    if it.layer != "surface_item":
        for o in others:
            if catalog.items[o.item_id].layer != it.layer:
                continue
            if cell_set & set(footprint_of(catalog, o)):
                raise fail("collision")
        return Placement(z=Z_OF_LAYER[it.layer], parent_uid=None)

    # surface_item
    surfaces = [o for o in others if catalog.items[o.item_id].layer == "furniture" and catalog.items[o.item_id].is_surface]
    surface_items = [o for o in others if catalog.items[o.item_id].layer == "surface_item"]
    parents: set[int] = set()
    for c in cells:
        under = [o for o in surfaces if c in footprint_of(catalog, o)]
        if len(under) != 1:
            raise fail("needs_surface")
        parents.add(under[0].uid)
        if any(c in footprint_of(catalog, o) for o in surface_items):
            raise fail("surface_occupied")
    if len(parents) != 1:
        raise fail("spans_multiple_surfaces")
    return Placement(z=Z_OF_LAYER["surface_item"], parent_uid=parents.pop())


def has_children(uid: int, rows: list[ItemRow]) -> bool:
    return any(r.parent_uid == uid for r in rows)
