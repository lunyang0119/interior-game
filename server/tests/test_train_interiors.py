"""data/train_interiors.json: /train/ compartment templates (world editor "열차 칸"), served in /api/catalog."""

import json

import pytest

from app import catalog as cm


def tpl(cols=7, rows=6, wall_rows=2, seed=None):
    return {"cols": cols, "rows": rows, "wall_rows": wall_rows, "spawn": {"x": 0, "y": wall_rows},
            "tiles": {"wall": ["tile_wall"] * wall_rows, "floor": "tile_floor"},
            "seed": seed if seed is not None else [{"item_id": "chair", "x": 1, "y": 3}, {"item_id": "frame", "x": 2, "y": 0}]}


def write(env, rooms):
    (env["data"] / "train_interiors.json").write_text(json.dumps({"rooms": rooms}), encoding="utf-8")


def test_absent_file_means_builtin(catalog):
    assert catalog.train == {} and catalog.public()["train"] is None


def test_templates_load_and_publish(env):
    write(env, {"curtain": tpl(), "light": tpl(seed=[])})
    c = cm.load()
    assert set(c.train) == {"curtain", "light"}
    pub = c.public()["train"]
    assert pub["curtain"]["seed"][0]["item_id"] == "chair" and pub["light"]["cols"] == 7


@pytest.mark.parametrize("rooms, why", [
    ({"tv": tpl()}, "unknown device"),
    ({"curtain": tpl(), "light": tpl(cols=8)}, "same cols"),
    ({"curtain": tpl(seed=[{"item_id": "nope", "x": 0, "y": 2}])}, "not an item"),
    ({"curtain": {**tpl(), "tiles": {"wall": ["tile_wall", "tile_wall"], "floor": "missing_tile"}}}, "not in manifest"),
    ({"curtain": tpl(cols=20)}, "out of range"),
    ({"curtain": tpl(rows=4, wall_rows=3)}, "out of range"),   # 1 floor row: a side door needs 2
])
def test_bad_templates_refuse_to_load(env, rooms, why):
    write(env, rooms)
    with pytest.raises(ValueError, match=why):
        cm.load()


def test_door_openings_and_corridor_layout(env):
    """`doors` per template (floor rows / columns) and the shared `layout` (gap, corridor art) load and publish."""
    rooms = {"curtain": {**tpl(), "doors": {"left": {"y": 2, "h": 3}, "top": {"x": 5, "w": 2}}}, "light": tpl()}
    (env["data"] / "train_interiors.json").write_text(json.dumps({
        "layout": {"gap": 2, "tiles": {"partition": "tile_wall", "corridor": "tile_floor", "side_door": None, "back_door": "gate"}},
        "rooms": rooms}), encoding="utf-8")
    c = cm.load()
    assert c.train["curtain"].doors.left.h == 3 and c.train["curtain"].doors.right is None and c.train["light"].doors is None
    pub = c.public()
    assert pub["train_layout"] == {"gap": 2, "tiles": {"partition": "tile_wall", "corridor": "tile_floor", "side_door": None, "back_door": "gate"}}
    assert pub["train"]["curtain"]["doors"]["top"] == {"x": 5, "w": 2}


@pytest.mark.parametrize("doors, layout, why", [
    ({"left": {"y": 1, "h": 2}}, None, "not floor rows"),          # y=1 is a wall row (wall_rows=2)
    ({"right": {"y": 5, "h": 2}}, None, "not floor rows"),         # runs past the last row (rows=6)
    ({"bottom": {"x": 6, "w": 2}}, None, "outside the compartment"),
    (None, {"gap": 5}, "less than or equal to 4"),
    (None, {"tiles": {"corridor": "nope"}}, "not in manifest"),
])
def test_bad_doors_and_layout_refuse_to_load(env, doors, layout, why):
    data = {"rooms": {"curtain": {**tpl(), **({"doors": doors} if doors else {})}}}
    if layout:
        data["layout"] = layout
    (env["data"] / "train_interiors.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match=why):
        cm.load()
