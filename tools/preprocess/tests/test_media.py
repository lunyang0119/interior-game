"""`preprocess.py media`: BGM naming (loose night_* = night, other loose = day) and sfx variants."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import preprocess as P  # noqa: E402


def _mp3(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"ID3")


def test_bgm_loose_files_split_by_night_prefix(tmp_path):
    src = tmp_path / "BGM"
    _mp3(src / "day" / "default-day.mp3")
    _mp3(src / "night" / "default-night.mp3")
    _mp3(src / "dock" / "seaside.mp3")
    _mp3(src / "dock" / "Night_ocean breeze.mp3")
    _mp3(src / "dock" / "night" / "late.mp3")
    _mp3(src / "field" / "meadow.mp3")  # no night tracks at all → empty night list (client falls back)
    _mp3(src / "legacy" / "old.mp3")
    out = tmp_path / "media" / "bgm"
    m = P.build_bgm_manifest(src, out)
    assert [t["title"] for t in m["default"]["day"]] == ["default-day"]
    assert [t["title"] for t in m["default"]["night"]] == ["default-night"]
    assert [t["title"] for t in m["dock"]["day"]] == ["seaside"]
    assert sorted(t["title"] for t in m["dock"]["night"]) == ["late", "ocean breeze"]  # prefix stripped
    assert [t["title"] for t in m["field"]["day"]] == ["meadow"] and m["field"]["night"] == []
    assert "legacy" not in m
    for lists in m.values():
        for tracks in lists.values():
            for t in tracks:
                assert (out / t["file"]).exists()


def test_sfx_variants_are_numbered_and_counted(tmp_path):
    src = tmp_path / "sfx"
    _mp3(src / "cat_meow-a.mp3")
    _mp3(src / "pets" / "cat_meow-b.mp3")
    _mp3(src / "cat_meow-c.mp3")
    _mp3(src / "UI" / "sell_coin.mp3")
    _mp3(src / "walking" / "wood_step.mp3")
    _mp3(src / "legacy" / "cat_old.mp3")
    out = tmp_path / "media" / "sfx"
    counts = P.copy_sfx(src, out)
    assert counts == {"cat": 3, "sell": 1, "step_wood": 1}
    assert sorted(p.name for p in out.glob("*.mp3")) == ["cat.mp3", "cat_2.mp3", "cat_3.mp3", "sell.mp3", "step_wood.mp3"]
    j = json.loads((out.parent / "sfx.json").read_text(encoding="utf-8"))
    assert j == {"kinds": ["cat", "sell", "step_wood"], "variants": counts}
