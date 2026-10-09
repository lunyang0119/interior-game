"""Unit tests for the preprocess build helpers (run: `pytest tools/preprocess/tests` from the repo root)."""

import json
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import preprocess as P  # noqa: E402


def _atlas(tmp_path: Path, colors: dict[str, tuple]) -> tuple[Path, Path]:
    """A fake previous atlas: one 16x16 solid frame per key, laid out left to right."""
    png = tmp_path / "old.png"
    js = tmp_path / "old.json"
    im = Image.new("RGBA", (16 * len(colors), 16), (0, 0, 0, 0))
    frames = {}
    for i, (key, rgba) in enumerate(colors.items()):
        im.paste(Image.new("RGBA", (16, 16), rgba), (i * 16, 0))
        frames[key] = {"frame": {"x": i * 16, "y": 0, "w": 16, "h": 16}}
    im.save(png)
    js.write_text(json.dumps({"frames": frames}), encoding="utf-8")
    return js, png


def test_missing_sheet_falls_back_to_frozen_frame(tmp_path: Path):
    js, png = _atlas(tmp_path, {"old_chair": (255, 0, 0, 255), "old_table": (0, 255, 0, 255)})
    live = tmp_path / "live.png"
    Image.new("RGBA", (32, 16), (0, 0, 255, 255)).save(live)
    slices = [
        {"key": "old_chair", "sheet": "gone", "x": 0, "y": 0, "w": 16, "h": 16},
        {"key": "old_table", "sheet": "gone", "x": 16, "y": 0, "w": 16, "h": 16},
        {"key": "new_lamp", "sheet": "live", "x": 0, "y": 0, "w": 16, "h": 16},
    ]
    frozen = P.load_frozen(js, png)
    atlas, atlas_json = P.pack_atlas(slices, {"live": live, "gone": tmp_path / "nope.png"},
                                     image_name="x.png", file_base=tmp_path, frozen=frozen)
    assert set(atlas_json["frames"]) == {"old_chair", "old_table", "new_lamp"}
    assert sorted(P.FROZEN_USED) == ["old_chair", "old_table"]
    f = atlas_json["frames"]["old_chair"]["frame"]
    assert atlas.getpixel((f["x"], f["y"])) == (255, 0, 0, 255)
    f = atlas_json["frames"]["new_lamp"]["frame"]
    assert atlas.getpixel((f["x"], f["y"])) == (0, 0, 255, 255)
    assert atlas_json["meta"]["image"] == "x.png"


def test_missing_source_without_frozen_frame_aborts(tmp_path: Path):
    js, png = _atlas(tmp_path, {"other": (1, 2, 3, 255)})
    frozen = P.load_frozen(js, png)
    with pytest.raises(SystemExit):
        P.pack_atlas([{"key": "nope", "sheet": "gone", "x": 0, "y": 0, "w": 16, "h": 16}],
                     {"gone": tmp_path / "nope.png"}, frozen=frozen)
    with pytest.raises(SystemExit):
        P.pack_atlas([{"key": "nope", "file": "missing.png"}], {}, file_base=tmp_path, frozen=None)


def test_file_slices_resolve_against_file_base(tmp_path: Path):
    (tmp_path / "sub").mkdir()
    Image.new("RGBA", (16, 32), (9, 9, 9, 255)).save(tmp_path / "sub" / "thing.png")
    atlas, atlas_json = P.pack_atlas([{"key": "thing", "file": "sub/thing.png"}], {}, file_base=tmp_path)
    assert atlas_json["frames"]["thing"]["frame"]["h"] == 32
    assert P.FROZEN_USED == []


def test_transparent_knocks_out_backdrop(tmp_path: Path):
    live = tmp_path / "live.png"
    im = Image.new("RGBA", (16, 16), (202, 226, 234, 255))
    im.putpixel((3, 3), (10, 20, 30, 255))
    im.save(live)
    atlas, atlas_json = P.pack_atlas(
        [{"key": "h", "sheet": "live", "x": 0, "y": 0, "w": 16, "h": 16, "transparent": [202, 226, 234]}],
        {"live": live})
    assert atlas.getpixel((0, 0)) == (0, 0, 0, 0)
    assert atlas.getpixel((3, 3)) == (10, 20, 30, 255)


def test_load_frozen_returns_none_without_previous_atlas(tmp_path: Path):
    assert P.load_frozen(tmp_path / "a.json", tmp_path / "a.png") is None


def test_set_of_slugs_sources_into_furniture_sets():
    mi = "Interior/moderninteriors-win/1_Interiors/16x16/Theme_Sorter/4_Bedroom_16x16.png"
    assert P.set_of({"key": "a", "sheet": mi, "x": 0, "y": 0, "w": 16, "h": 16}) == "mi_bedroom"
    assert P.set_of({"key": "b", "sheet": "pi_beds_br"}) == "pi_bedroom"          # alias table merges a pack
    assert P.set_of({"key": "c", "sheet": "interiors"}) == "mi_free"
    assert P.set_of({"key": "d", "sheet": "furniture03"}) == "furniture03"        # plain SHEETS key stays itself
    assert P.set_of({"key": "e", "file": "Furniture Assets/Rooms/Bath.png"}) == "furniture_assets"
    assert P.set_of({"key": "f", "parts": [{"sheet": mi, "x": 0, "y": 0, "w": 16, "h": 16}]}) == "mi_bedroom"
    assert P.set_of({"key": "g"}) is None
    with pytest.raises(SystemExit):
        P.set_of({"key": "h", "sheet": "Interior/my_sheet_thing.png"})


def test_atlas_keys_carry_sets_only_for_interiors():
    atlas = {"frames": {"a": {"frame": {"x": 0, "y": 0, "w": 16, "h": 32}}}}
    sl = [{"key": "a", "sheet": "pi_beds_br", "step": "wood"}]
    assert P.atlas_keys(atlas, sl, sets=True)["a"] == {"w": 16, "h": 32, "cw": 1, "ch": 2, "set": "pi_bedroom", "step": "wood"}
    assert "set" not in P.atlas_keys(atlas, sl)["a"]


def test_build_cat_cuts_only_real_frames_and_skips_the_title_row(tmp_path: Path):
    # a fake Cats/<variant>.png: 6 sections × 4 cells, title row 0, 8 directions × 2 rows below it
    cell = P.C.CAT_CELL
    im = Image.new("RGBA", (32 * cell, 17 * cell), (0, 0, 0, 0))
    for col in range(24):  # title text across every section: must never become a frame
        im.putpixel((col * cell + 1, 1), (255, 255, 255, 255))
    # section 0 (sit): 5 frames facing down (4 on the first row + 1 on the second), 4 facing right
    for col in range(4):
        im.putpixel((col * cell + 5, 1 * cell + 5), (200, 100, 0, 255))
        im.putpixel((col * cell + 5, 5 * cell + 5), (200, 100, 0, 255))
    im.putpixel((5, 2 * cell + 5), (200, 100, 0, 255))
    # every other (section, cardinal direction): one frame
    for si in range(1, len(P.C.CAT_SECTIONS)):
        for block in P.C.CAT_DIR_BLOCKS.values():
            im.putpixel((si * 4 * cell + 5, (1 + block * 2) * cell + 5), (200, 100, 0, 255))
    for d, block in P.C.CAT_DIR_BLOCKS.items():
        if d in ("up", "left"):
            im.putpixel((5, (1 + block * 2) * cell + 5), (200, 100, 0, 255))
    src = tmp_path / "ginger_0.png"
    im.save(src)
    out = tmp_path / "cat"
    entry = P.build_cat("ginger_0", out, src)
    assert entry is not None
    assert entry["variant"] == "ginger_0" and entry["file"] == "gen/cat/ginger_0.png"
    assert entry["frameW"] == cell and entry["frameH"] == cell
    assert entry["anims"]["sit_down"] == [0, 4]
    assert entry["anims"]["sit_right"] == [5, 8]
    assert entry["anims"]["sit_up"] == [9, 9] and entry["anims"]["sit_left"] == [10, 10]
    assert entry["anims"]["look_down"] == [11, 11] and entry["anims"]["walk_down"] == [19, 19]
    total = max(e for _, e in entry["anims"].values()) + 1
    strip = Image.open(out / "ginger_0.png")
    assert strip.size == (total * cell, cell)
    assert strip.getpixel((5, 5)) == (200, 100, 0, 255)   # first frame = sit_down frame 0
    assert P.build_cat("nope", out, tmp_path / "nope.png") is None
