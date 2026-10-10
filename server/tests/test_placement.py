import pytest

from app.errors import ApiError
from app.placement import ItemRow, has_children, validate_place


def row(uid, item_id, x, y, z=1, parent=None, span=None):
    return ItemRow(uid=uid, item_id=item_id, x=x, y=y, z=z, parent_uid=parent, placed_by="lun", ts=0, span=span)


def err(fn):
    with pytest.raises(ApiError) as e:
        fn()
    return e.value.code


def test_unknown_item(catalog):
    assert err(lambda: validate_place(catalog, [], "nope", 1, 1)) == "unknown_item"


def test_out_of_bounds_and_blocked(catalog):
    assert err(lambda: validate_place(catalog, [], "table", 7, 2)) == "out_of_bounds"  # 2 wide, cols=8
    assert err(lambda: validate_place(catalog, [], "chair", 7, 5)) == "out_of_bounds"  # blocked cell


def test_cell_type(catalog):
    assert err(lambda: validate_place(catalog, [], "chair", 1, 0)) == "bad_cell_type"  # wall row
    assert err(lambda: validate_place(catalog, [], "frame", 1, 3)) == "bad_cell_type"  # floor row
    assert validate_place(catalog, [], "frame", 1, 0).z == 1
    assert validate_place(catalog, [], "chair", 1, 1).z == 1


def test_partition_walls_stand_on_the_floor_like_furniture(catalog):
    """A `partition` wall sprite: floor rows only, collides with furniture (and other partitions), furniture z."""
    assert err(lambda: validate_place(catalog, [], "divider", 1, 0)) == "bad_cell_type"  # not on the wall rows
    p = validate_place(catalog, [], "divider", 1, 3)
    assert p.z == 1 and p.parent_uid is None
    assert err(lambda: validate_place(catalog, [row(1, "chair", 2, 3)], "divider", 1, 3)) == "collision"
    assert err(lambda: validate_place(catalog, [row(1, "divider", 1, 3)], "chair", 2, 3)) == "collision"
    assert err(lambda: validate_place(catalog, [row(1, "divider", 1, 3)], "gate", 2, 3)) == "collision"
    validate_place(catalog, [row(1, "rug", 1, 3)], "divider", 1, 3)  # rugs are another layer
    assert err(lambda: validate_place(catalog, [], "divider", 3, 3, room_id="house_a")) == "out_of_bounds"  # pond tile at (4,3)


def test_wall_decor_hangs_on_a_partition(catalog):
    """`wall` decor may sit on floor cells covered by a partition's face (sprite rows up from its feet); the
    partition becomes its parent and it gets the "hung" z. divider: footprint 2×1, picture 2 rows (manifest ch)."""
    divider = [row(1, "divider", 1, 3)]  # feet on row 3 → face rows 2..3, cols 1..2
    p = validate_place(catalog, divider, "frame", 1, 2)
    assert p.z == 2 and p.parent_uid == 1
    assert validate_place(catalog, divider, "frame", 2, 3).parent_uid == 1
    assert err(lambda: validate_place(catalog, divider, "frame", 1, 1)) == "bad_cell_type"  # above the face
    assert err(lambda: validate_place(catalog, divider, "frame", 3, 3)) == "bad_cell_type"  # next to it
    assert err(lambda: validate_place(catalog, [], "frame", 1, 3)) == "bad_cell_type"  # nothing to hang on
    assert err(lambda: validate_place(catalog, divider, "paper", 1, 3)) == "bad_cell_type"  # wallpaper never hangs
    # frames collide with frames on the face, and the partition cannot go while something hangs on it
    hung = divider + [row(2, "frame", 1, 2, z=2, parent=1)]
    assert err(lambda: validate_place(catalog, hung, "frame", 1, 2)) == "collision"
    assert has_children(1, hung)
    # a wide banner may span two partitions side by side; the one under its first cell is the parent
    two = [row(1, "divider", 1, 3), row(2, "divider", 3, 3)]
    assert validate_place(catalog, two, "banner", 2, 3).parent_uid == 1
    assert validate_place(catalog, two, "banner", 1, 2).parent_uid == 1
    assert err(lambda: validate_place(catalog, two, "banner", 3, 3)) == "bad_cell_type"  # col 5 has no partition
    # on the wall rows nothing changes
    assert validate_place(catalog, divider, "frame", 1, 0).parent_uid is None
    # seeds hang too (cell type is enforced even when relaxed)
    assert validate_place(catalog, divider, "frame", 1, 2, relaxed=True).parent_uid == 1
    assert err(lambda: validate_place(catalog, [], "frame", 1, 2, relaxed=True)) == "bad_cell_type"


def test_rugs_lie_over_floor_patterns(catalog):
    """`rug`-tagged floor items are their own collision group above untagged floor patterns."""
    pattern = [row(1, "pattern", 2, 2, z=0)]
    assert validate_place(catalog, pattern, "rug", 2, 2).z == 1  # rug over pattern
    assert err(lambda: validate_place(catalog, pattern, "pattern", 3, 3)) == "collision"  # pattern vs pattern
    rug = [row(2, "rug", 2, 2, z=1)]
    assert validate_place(catalog, rug, "pattern", 2, 2).z == 0  # pattern under a rug
    assert validate_place(catalog, rug, "chair", 2, 2).z == 1  # furniture on a rug
    assert err(lambda: validate_place(catalog, [], "rug", 3, 2, room_id="house_a")) == "out_of_bounds"  # pond at (4,3)
    assert err(lambda: validate_place(catalog, [], "pattern", 3, 2, room_id="house_a")) == "out_of_bounds"


def test_wallpaper_under_wall_decor(catalog):
    assert err(lambda: validate_place(catalog, [], "paper", 1, 3)) == "bad_cell_type"  # floor row
    paper = [row(1, "paper", 1, 0, z=0)]
    assert validate_place(catalog, paper, "frame", 1, 0).z == 1  # decor hangs over wallpaper
    assert err(lambda: validate_place(catalog, paper, "paper", 2, 0)) == "collision"  # wallpaper vs wallpaper
    assert validate_place(catalog, paper, "paper", 3, 0).z == 0


def test_furniture_collision_but_rug_ok(catalog):
    others = [row(1, "table", 2, 2)]
    assert err(lambda: validate_place(catalog, others, "chair", 3, 2)) == "collision"
    assert validate_place(catalog, others, "chair", 4, 2).z == 1
    assert validate_place(catalog, others, "rug", 2, 2).z == 1  # floor under furniture is fine
    rugs = [row(2, "rug", 2, 2, z=1)]
    assert err(lambda: validate_place(catalog, rugs, "rug", 3, 3)) == "collision"


def test_cup_needs_table(catalog):
    assert err(lambda: validate_place(catalog, [], "cup", 2, 2)) == "needs_surface"
    chair = [row(1, "chair", 2, 2)]  # not is_surface
    assert err(lambda: validate_place(catalog, chair, "cup", 2, 2)) == "needs_surface"
    table = [row(1, "table", 2, 2)]
    p = validate_place(catalog, table, "cup", 3, 2)
    assert p.z == 2 and p.parent_uid == 1


def test_one_surface_item_per_cell(catalog):
    others = [row(1, "table", 2, 2), row(2, "cup", 2, 2, z=2, parent=1)]
    assert err(lambda: validate_place(catalog, others, "cup", 2, 2)) == "surface_occupied"
    assert validate_place(catalog, others, "cup", 3, 2).parent_uid == 1


def test_tray_cannot_span_two_tables(catalog):
    others = [row(1, "table", 0, 2), row(2, "table", 2, 2)]
    assert err(lambda: validate_place(catalog, others, "tray", 1, 2)) == "spans_multiple_surfaces"
    assert validate_place(catalog, others, "tray", 2, 2).parent_uid == 2


def test_has_children(catalog):
    rows = [row(1, "table", 2, 2), row(2, "cup", 2, 2, z=2, parent=1)]
    assert has_children(1, rows)
    assert not has_children(2, rows)


def test_wallpaper_span(catalog):
    from app.placement import price_of
    assert validate_place(catalog, [], "paper", 0, 0, span=8).z == 0  # whole wall (cols=8)
    assert err(lambda: validate_place(catalog, [], "paper", 6, 0, span=3)) == "out_of_bounds"
    assert err(lambda: validate_place(catalog, [], "paper", 0, 0, span=9)) == "bad_span"
    assert err(lambda: validate_place(catalog, [], "chair", 2, 2, span=2)) == "bad_span"  # not wallpaper
    wide = [row(1, "paper", 0, 0, z=0, span=5)]
    assert err(lambda: validate_place(catalog, wide, "paper", 4, 0, span=1)) == "collision"  # cell 4 is covered
    assert validate_place(catalog, wide, "paper", 5, 0, span=3).z == 0
    paper = catalog.items["paper"]
    assert price_of(paper, 5) == 75 and price_of(paper, None) == 30  # per column; None → item.w (2)
    assert price_of(catalog.items["chair"], None) == 50


def test_unwalkable_tile_blocks_furniture_and_rugs(catalog):
    # house_a paints tile_water (walk:false) at (4,3)
    assert err(lambda: validate_place(catalog, [], "chair", 4, 3, room_id="house_a")) == "out_of_bounds"
    assert err(lambda: validate_place(catalog, [], "rug", 3, 2, room_id="house_a")) == "out_of_bounds"  # 2x2 touches (4,3)
    validate_place(catalog, [], "chair", 3, 3, room_id="house_a")
    validate_place(catalog, [], "frame", 4, 0, room_id="house_a")  # wall layer never looks at floor tiles
    # seeds are relaxed: the designer may put junk in the pond on purpose
    validate_place(catalog, [], "chair", 4, 3, room_id="house_a", relaxed=True)
