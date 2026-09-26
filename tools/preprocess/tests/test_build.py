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
