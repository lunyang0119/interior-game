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


def _fake_cat_sheet(tmp_path: Path) -> Path:
    """A fake Cats/<variant>.png: 6 sections × 4 cells, title row 0, 8 directions × 2 rows below it."""
    cell = P.C.CAT_CELL
    im = Image.new("RGBA", (32 * cell, 17 * cell), (0, 0, 0, 0))
    for col in range(24):  # title text across every section: must never become a frame
        im.putpixel((col * cell + 1, 1), (255, 255, 255, 255))
    # section 0 (sit): 5 frames facing down (4 on the first row + 1 on the second), 4 facing right
    right = 1 + P.C.CAT_DIR_BLOCKS["right"] * 2
    for col in range(4):
        im.putpixel((col * cell + 5, 1 * cell + 5), (200, 100, 0, 255))
        im.putpixel((col * cell + 5, right * cell + 5), (200, 100, 0, 255))
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
    return src


def test_cat_directions_follow_the_sheet():
    # the sheet goes counter-clockwise from down: rows 5-6 face left, rows 13-14 face right
    assert P.C.CAT_DIR_BLOCKS == {"down": 0, "right": 6, "up": 4, "left": 2}


def test_build_cat_default_cuts_only_real_frames_and_skips_the_title_row(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(P.C, "CAT_ANIMS_FILE", tmp_path / "none.json")
    src = _fake_cat_sheet(tmp_path)
    cell = P.C.CAT_CELL
    out = tmp_path / "cat"
    entry = P.build_cat("ginger_0", out, src)
    assert entry is not None
    assert entry["variant"] == "ginger_0" and entry["file"] == "gen/cat/ginger_0.png"
    assert entry["frameW"] == cell and entry["frameH"] == cell
    a = entry["anims"]
    assert a["sit_down"] == {"frames": [0, 1, 2, 3, 4], "fps": 6, "loop": False}
    assert a["sit_right"]["frames"] == [5, 6, 7, 8]
    assert a["walk_down"]["loop"] is True and a["walk_down"]["fps"] == 8
    total = 1 + max(i for v in a.values() for i in v["frames"])
    strip = Image.open(out / "ginger_0.png")
    assert strip.size == (total * cell, cell)
    assert strip.getpixel((5, 5)) == (200, 100, 0, 255)   # first frame = sit_down frame 0
    assert P.build_cat("nope", out, tmp_path / "nope.png") is None


def test_build_cat_from_edited_anims_reuses_cells_and_keeps_order(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(P.C, "CAT_ANIMS_FILE", tmp_path / "none.json")
    src = _fake_cat_sheet(tmp_path)
    im = Image.open(src).convert("RGBA")
    anims = P.cat_default_anims(im)
    anims["sit_down"] = {"frames": [[2, 1], [0, 1], [2, 1]], "fps": 3, "loop": True}  # reordered, a cell twice
    assert P.validate_cat_anims(anims, im) is None
    entry = P.build_cat("ginger_0", tmp_path / "cat", src, anims)
    assert entry["anims"]["sit_down"] == {"frames": [0, 1, 0], "fps": 3, "loop": True}
    # bad edits are refused with a reason
    bad = dict(anims, sit_down={"frames": [[3, 2]], "fps": 6, "loop": False})  # an empty cell
    assert "빈 칸" in P.validate_cat_anims(bad, im)
    bad = dict(anims, sit_down={"frames": [[0, 0]], "fps": 6, "loop": False})  # the title row
    assert "제목" in P.validate_cat_anims(bad, im)
    bad = dict(anims, sit_down={"frames": [], "fps": 6, "loop": False})
    assert "하나도" in P.validate_cat_anims(bad, im)
    bad = {k: v for k, v in anims.items() if k != "run_left"}
    assert "빠짐" in P.validate_cat_anims(bad, im)


def test_loot_icons_from_slice_keys_paths_and_frame_lists(tmp_path: Path, monkeypatch):
    """copy_loot_icons: an ore's `sprite` (an interior slice key) is cropped like the atlas, an asset path is copied,
    a {file,x,y} cell is cropped from the sheet, and a list writes <name>_1.png, <name>_2.png."""
    sheet = tmp_path / "props.png"
    im = Image.new("RGBA", (32, 16), (0, 0, 0, 0))
    im.paste(Image.new("RGBA", (16, 16), (200, 50, 50, 255)), (0, 0))
    im.paste(Image.new("RGBA", (16, 16), (50, 200, 50, 255)), (16, 0))
    im.save(sheet)
    assets = tmp_path / "assets"
    (assets / "Map").mkdir(parents=True)
    Image.new("RGBA", (8, 8), (0, 0, 200, 255)).save(assets / "Map" / "hole.png")
    data = tmp_path / "mine.json"
    data.write_text(json.dumps({"ores": [{"id": "stone", "sprite": "mine_stone"}, {"id": "coal", "sprite": "mine_coal", "icon": "Map/hole.png"},
                                         {"id": "gone", "sprite": "not_a_slice"}],
                                "pickaxe": ["pick_a", "pick_b"]}), encoding="utf-8")
    slices = [{"key": "mine_stone", "sheet": "props", "x": 0, "y": 0, "w": 16, "h": 16},
              {"key": "mine_coal", "sheet": "props", "x": 16, "y": 0, "w": 16, "h": 16},
              {"key": "pick_a", "sheet": "props", "x": 0, "y": 0, "w": 8, "h": 8},
              {"key": "pick_b", "sheet": "props", "x": 16, "y": 0, "w": 8, "h": 8}]
    monkeypatch.setattr(P.C, "OUT_DIR", tmp_path / "gen")
    monkeypatch.setattr(P.C, "ASSETS", assets)
    monkeypatch.setattr(P.C, "all_sheets", lambda: {"props": sheet})
    out = P.copy_loot_icons(data, "ores", "mine", {"pickaxe": ["pick_a", "pick_b"], "ladder": {"file": "Map/hole.png", "x": 0, "y": 0, "w": 8, "h": 8}},
                            slices=slices)
    assert out == {"icons": ["stone", "coal", "pickaxe_1", "pickaxe_2", "ladder"]}  # `gone` is skipped with a warning
    gen = tmp_path / "gen" / "mine"
    assert Image.open(gen / "stone.png").getpixel((0, 0)) == (200, 50, 50, 255)
    assert Image.open(gen / "coal.png").size == (8, 8)  # the explicit icon path wins over the sprite
    assert Image.open(gen / "pickaxe_2.png").getpixel((0, 0)) == (50, 200, 50, 255)
    assert Image.open(gen / "ladder.png").size == (8, 8) and not (gen / "gone.png").exists()


def test_loop_strip_preset_samples_every_direction_and_keeps_its_frame_size(tmp_path: Path):
    """A 36x30 hover loop of 14 frames → 48 frames of 36x30; left is mirrored, the manifest lists the size."""
    import config as C
    fw, fh, n = 36, 30, 14
    strip = Image.new("RGBA", (fw * n, fh), (0, 0, 0, 0))
    for i in range(n):  # frame i: a 2px dot at x = 2 + i so frames are distinguishable, plus a left-edge marker
        strip.paste(Image.new("RGBA", (2, 2), (255, 0, 0, 255)), (i * fw + 2 + i, 10))
        strip.paste(Image.new("RGBA", (1, fh), (0, 0, 255, 255)), (i * fw, 0))
    src = tmp_path / "Drone_36x30.png"
    strip.save(src)
    v = {"name": "Drone", "strip": src, "frame": (fw, fh), "style": 10_000, "color": 0}
    entry = P.build_char_layer("preset", [{"name": "none", "sheet": None, "style": 0, "color": 0}, v], tmp_path / "out")
    assert entry["count"] == 2 and entry["sizes"] == {"1": [fw, fh]} and entry["names"] == ["none", "Drone"]
    none = Image.open(tmp_path / "out" / "0.png")
    assert none.size == (C.FRAME_W * 48, C.FRAME_H)  # the none variant keeps the character frame
    sheet = Image.open(tmp_path / "out" / "1.png").convert("RGBA")
    assert sheet.size == (fw * 48, fh)
    frames = [sheet.crop((k * fw, 0, (k + 1) * fw, fh)) for k in range(48)]
    picked = [(k * n) // C.FRAMES_PER_DIR for k in range(C.FRAMES_PER_DIR)]  # 0,2,4,7,9,11
    for di, d in enumerate(C.DIRS):
        for k in range(C.FRAMES_PER_DIR):
            fr = frames[di * C.FRAMES_PER_DIR + k]
            dot_x = 2 + picked[k]
            if d == "left":
                assert fr.getpixel((fw - 1, 0))[2] == 255 and fr.getpixel((fw - 1 - dot_x, 10))[0] == 255  # mirrored
            else:
                assert fr.getpixel((0, 0))[2] == 255 and fr.getpixel((dot_x, 10))[0] == 255
    assert all(a.tobytes() == b.tobytes() for a, b in zip(frames[24:], frames[:24]))  # idle = the same frames as run


def test_loop_strip_with_wrong_height_aborts(tmp_path: Path):
    src = tmp_path / "Ghost_20x20.png"
    Image.new("RGBA", (40, 19), (0, 0, 0, 0)).save(src)
    with pytest.raises(SystemExit):
        P._loop_strip({"name": "Ghost", "strip": src, "frame": (20, 20)}, "run")


def test_anim_slice_packs_frames_and_manifest_lists_only_the_key(tmp_path: Path, monkeypatch):
    """`anim` = a folder of frames under assets/graphic → atlas frames key, key#0..n-1; the manifest key carries
    anim {frames, fps} and the #i frames are not keys of their own."""
    import config as C
    monkeypatch.setattr(C, "ASSETS", tmp_path)
    d = tmp_path / "fx" / "steam"
    d.mkdir(parents=True)
    for i, col in enumerate([(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255)]):
        Image.new("RGBA", (8, 8), col).save(d / f"steam_{i + 1:02d}.png")
    slices = [{"key": "fx_steam", "anim": "fx/steam", "fps": 6}]
    atlas, js = P.pack_atlas(slices, sheet_paths={}, file_base=tmp_path)
    assert set(js["frames"]) == {"fx_steam", "fx_steam#0", "fx_steam#1", "fx_steam#2"}
    f0, f1 = js["frames"]["fx_steam#0"]["frame"], js["frames"]["fx_steam#1"]["frame"]
    assert atlas.getpixel((f0["x"], f0["y"])) == (255, 0, 0, 255) and atlas.getpixel((f1["x"], f1["y"])) == (0, 255, 0, 255)
    keys = P.atlas_keys(js, slices, sets=True)
    assert set(keys) == {"fx_steam"} and keys["fx_steam"]["anim"] == {"frames": 3, "fps": 6}
    # frames of different sizes are refused
    Image.new("RGBA", (9, 8), (0, 0, 0, 255)).save(d / "steam_04.png")
    with pytest.raises(SystemExit):
        P.anim_frames(slices[0])


def test_frames_anim_slice_reuses_other_slices_as_frames(tmp_path: Path):
    """`frames` = keys of other slices of the same atlas (a lamp cut as on/off pieces): packed as key#i,
    frame 0 is the key itself; an unknown or animated frame key aborts."""
    sheet = tmp_path / "lamps.png"
    im = Image.new("RGBA", (32, 16), (0, 0, 0, 0))
    im.paste(Image.new("RGBA", (16, 16), (255, 200, 0, 255)), (0, 0))
    im.paste(Image.new("RGBA", (16, 16), (40, 40, 40, 255)), (16, 0))
    im.save(sheet)
    slices = [
        {"key": "lamp_on", "sheet": "lamps", "x": 0, "y": 0, "w": 16, "h": 16},
        {"key": "lamp_off", "sheet": "lamps", "x": 16, "y": 0, "w": 16, "h": 16},
        {"key": "fx_blink", "frames": ["lamp_on", "lamp_off", "lamp_on"], "fps": 3},
    ]
    atlas, js = P.pack_atlas(slices, sheet_paths={"lamps": sheet})
    assert set(js["frames"]) == {"lamp_on", "lamp_off", "fx_blink", "fx_blink#0", "fx_blink#1", "fx_blink#2"}
    f = js["frames"]["fx_blink#1"]["frame"]
    assert atlas.getpixel((f["x"], f["y"])) == (40, 40, 40, 255)
    f = js["frames"]["fx_blink"]["frame"]
    assert atlas.getpixel((f["x"], f["y"])) == (255, 200, 0, 255)
    keys = P.atlas_keys(js, slices)
    assert keys["fx_blink"]["anim"] == {"frames": 3, "fps": 3} and "anim" not in keys["lamp_on"]
    with pytest.raises(SystemExit):
        P.pack_atlas(slices + [{"key": "bad", "frames": ["nope"]}], sheet_paths={"lamps": sheet})
    with pytest.raises(SystemExit):
        P.pack_atlas(slices + [{"key": "bad", "frames": ["fx_blink"]}], sheet_paths={"lamps": sheet})


def test_directional_strip_preset_uses_one_row_per_direction(tmp_path: Path):
    """A strip 4 rows tall = one loop per direction (DIRS order), nothing mirrored."""
    import config as C
    fw, fh, n = 16, 48, 8
    strip = Image.new("RGBA", (fw * n, fh * len(C.DIRS)), (0, 0, 0, 0))
    for di in range(len(C.DIRS)):  # row di: a marker on the left edge coloured by direction
        for i in range(n):
            strip.paste(Image.new("RGBA", (1, fh), (di * 50, 0, 0, 255)), (i * fw, di * fh))
    src = tmp_path / "Ghost_16x48.png"
    strip.save(src)
    out = P._loop_strip({"name": "Ghost", "strip": src, "frame": (fw, fh)}, "run")
    assert out.size == (fw * C.FRAMES_PER_DIR * len(C.DIRS), fh)
    for di in range(len(C.DIRS)):
        fr = out.crop((di * C.FRAMES_PER_DIR * fw, 0, (di * C.FRAMES_PER_DIR + 1) * fw, fh))
        assert fr.getpixel((0, 0)) == (di * 50, 0, 0, 255)  # its own row, left edge still on the left
    with pytest.raises(SystemExit):  # 3 rows is neither a loop nor one per direction
        Image.new("RGBA", (fw * n, fh * 3), (0, 0, 0, 0)).save(src)
        P._loop_strip({"name": "Ghost", "strip": src, "frame": (fw, fh)}, "run")
