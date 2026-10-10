"""Pure placement rules. No DB access here so it is trivial to unit test.

Rules (see plan §3):
1. item exists, footprint inside the room, no blocked cells, no unwalkable tiles (walk:false) under
   furniture or rugs
2. every footprint cell has the right type for the layer (wallpaper/wall ↔ wall rows, else floor);
   a `partition`-tagged wall sprite is the exception: it stands on floor rows — and `wall` decor may instead
   hang on a partition's face (floor cells covered by a partition's sprite, see partition_face); the partition
   under its first cell becomes its parent (so it goes when the partition goes), z = "hung"
3. wallpaper/wall/floor/furniture only collide with items of the same collision layer
   (so frames, doors and chalkboards can hang over wallpaper; partitions collide with furniture;
   `rug`-tagged floor items lie over untagged floor patterns)
4. surface_item needs exactly one is_surface furniture under every cell, the same
   one for all cells, and no other surface_item in those cells

`others` must be the rows of the same room; the caller filters by room_id.

`relaxed=True` is for seeded (pre-placed) items: the room designer may hang a footprint past the edge for
perspective or overlap furniture on purpose, so bounds, blocked cells and same-layer collisions are skipped.
Wall/floor row type and the surface rules still apply (they drive rendering).
"""

from __future__ import annotations

from dataclasses import dataclass

from .catalog import DEFAULT_ROOM, Catalog, Item, Z_OF_LAYER
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
    # note items only (TAG_NOTE): the text, who wrote it last, when
    note: str | None = None
    note_by: str | None = None
    note_ts: int | None = None


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


def partition_face(catalog: Catalog, row: ItemRow) -> set[Cell]:
    """Cells of a partition's visible wall face: its columns, `face_rows` rows up from the footprint bottom.
    Empty for anything that is not a partition."""
    it = catalog.items[row.item_id]
    if not it.is_partition:
        return set()
    bottom = row.y + it.h - 1
    return set(footprint(row.x, bottom - it.face_rows + 1, it.w, it.face_rows))


def hanger_of(catalog: Catalog, others: list[ItemRow], cells: list[Cell]) -> ItemRow | None:
    """The partition a wall decor with this footprint hangs on: every cell must lie on some partition's face;
    the one under the first cell is returned (it becomes the parent)."""
    first: ItemRow | None = None
    covered: set[Cell] = set()
    for o in others:
        face = partition_face(catalog, o)
        if not face:
            continue
        if first is None and cells[0] in face:
            first = o
        covered |= face
    return first if first is not None and all(c in covered for c in cells) else None


def validate_place(catalog: Catalog, others: list[ItemRow], item_id: str, x: int, y: int,
                   span: int | None = None, room_id: str | None = None, relaxed: bool = False) -> Placement:
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
    if not relaxed and any(not room.in_bounds(cx, cy) or (cx, cy) in blocked for cx, cy in cells):
        raise fail("out_of_bounds")
    # floor things cannot sit on water etc. (wall layers never touch floor tiles; surface items need a table)
    if not relaxed and it.collision_layer in ("furniture", "floor", "rug") and any(not catalog.tile_walkable(room, cx, cy) for cx, cy in cells):
        raise fail("out_of_bounds")

    want = "wall" if it.on_wall else "floor"
    hanger: ItemRow | None = None  # the partition a wall decor hangs on when it is not on the wall rows
    if any(room.cell_type(cx, cy) != want for cx, cy in cells):
        if it.can_hang and all(room.cell_type(cx, cy) == "floor" for cx, cy in cells):
            hanger = hanger_of(catalog, others, cells)
        if hanger is None:
            raise fail("bad_cell_type")

    cell_set = set(cells)

    if it.layer != "surface_item":
        for o in [] if relaxed else others:
            if catalog.items[o.item_id].collision_layer != it.collision_layer:
                continue
            if cell_set & set(footprint_of(catalog, o)):
                raise fail("collision")
        if hanger is not None:
            return Placement(z=Z_OF_LAYER["hung"], parent_uid=hanger.uid)
        return Placement(z=Z_OF_LAYER[it.collision_layer], parent_uid=None)

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
