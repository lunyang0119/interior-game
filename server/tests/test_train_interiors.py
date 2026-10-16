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
