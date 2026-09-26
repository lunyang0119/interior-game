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
    assert validate_place(catalog, others, "rug", 2, 2).z == 0  # floor under furniture is fine
    rugs = [row(2, "rug", 2, 2, z=0)]
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
