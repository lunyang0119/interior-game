"""`shrink`: 32px sheets → 16px copies (nearest for 2×-upscaled art, box for native hi-res art)."""

import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import preprocess as P  # noqa: E402


def _upscaled(colors: list[list[tuple]]) -> Image.Image:
    """A 2× nearest upscale of a tiny image."""
    h, w = len(colors), len(colors[0])
    small = Image.new("RGBA", (w, h))
    for y, row in enumerate(colors):
        for x, c in enumerate(row):
            small.putpixel((x, y), c)
    return small.resize((w * 2, h * 2), Image.NEAREST)


def test_auto_picks_nearest_for_blocky_art_and_restores_pixels():
    src = _upscaled([[(255, 0, 0, 255), (0, 255, 0, 255)], [(0, 0, 255, 255), (0, 0, 0, 0)]])
    assert P.is_blocky(src, 2)
    out, used = P.shrink_image(src, 0.5, "auto")
    assert used == "nearest" and out.size == (2, 2)
    assert out.getpixel((0, 0)) == (255, 0, 0, 255) and out.getpixel((1, 1)) == (0, 0, 0, 0)


def test_auto_picks_box_for_native_hires_art():
    im = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    im.putpixel((0, 0), (255, 255, 255, 255))  # a lone pixel breaks the 2×2 blocks
    assert not P.is_blocky(im, 2)
    out, used = P.shrink_image(im, 0.5, "auto")
    assert used == "box" and out.size == (2, 2)
    r, g, b, a = out.getpixel((0, 0))
    assert a == 64 and r == g == b == 255  # premultiplied average keeps the colour, only alpha drops


def test_shrunk_path_flattens_under_root(monkeypatch, tmp_path):
    assets = tmp_path / "graphic"
    (assets / "Interior" / "pack" / "32x32").mkdir(parents=True)
    monkeypatch.setattr(P.C, "ASSETS", assets)
    src = assets / "Interior" / "pack" / "32x32" / "Beds.png"
    assert P.shrunk_path(src) == assets / "Interior" / "_16px" / "pack__32x32__Beds.png"
    assert P.shrunk_path(tmp_path / "elsewhere.png", "Map") == assets / "Map" / "_16px" / "elsewhere.png"


def test_shrink_sheet_writes_file(monkeypatch, tmp_path):
    assets = tmp_path / "graphic"
    (assets / "Map" / "x").mkdir(parents=True)
    monkeypatch.setattr(P.C, "ASSETS", assets)
    src = assets / "Map" / "x" / "tiles.png"
    _upscaled([[(1, 2, 3, 255)] * 8] * 8).save(src)
    out, used = P.shrink_sheet(src)
    assert out == assets / "Map" / "_16px" / "x__tiles.png" and out.exists() and used == "nearest"
    with Image.open(out) as im:
        assert im.size == (8, 8)
