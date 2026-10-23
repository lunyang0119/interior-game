"""`detect_boxes`: the editor's 자동 자르기 (POST /api/autoslice)."""

import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import preprocess as P  # noqa: E402


def _sheet(rects, size=(64, 48), bg=(0, 0, 0, 0)) -> Image.Image:
    im = Image.new("RGBA", size, bg)
    d = ImageDraw.Draw(im)
    for x, y, w, h in rects:
        d.rectangle([x, y, x + w - 1, y + h - 1], fill=(200, 50, 50, 255))
    return im


def test_blob_boxes_are_tight_and_sorted():
    im = _sheet([(30, 2, 5, 6), (3, 20, 10, 4), (2, 2, 7, 7)])
    assert P.detect_boxes(im)["boxes"] == [[2, 2, 7, 7], [30, 2, 5, 6], [3, 20, 10, 4]]


def test_diagonal_pixels_join_and_matches_find_components():
    im = _sheet([(10, 10, 3, 3), (13, 13, 3, 3), (40, 5, 2, 9)])
    assert P.detect_boxes(im, min_px=1)["boxes"] == [[40, 5, 2, 9], [10, 10, 6, 6]]
    assert sorted(map(tuple, P.detect_boxes(im, min_px=1)["boxes"])) == sorted(P.find_components(im))


def test_gap_merges_near_regions_only():
    im = _sheet([(4, 4, 6, 6), (12, 4, 6, 6), (40, 4, 6, 6)])  # 2 px apart, then far away
    assert len(P.detect_boxes(im)["boxes"]) == 3
    assert P.detect_boxes(im, gap=2)["boxes"] == [[4, 4, 14, 6], [40, 4, 6, 6]]


def test_gap_at_sheet_edge_keeps_real_bounds():
    im = _sheet([(0, 0, 5, 5), (6, 0, 4, 4)], size=(32, 32))
    assert P.detect_boxes(im, gap=2)["boxes"] == [[0, 0, 10, 5]]


def test_min_px_drops_specks():
    im = _sheet([(1, 1, 2, 2), (10, 10, 8, 3)])
    assert P.detect_boxes(im, min_px=6)["boxes"] == [[10, 10, 8, 3]]


def test_snap_grid_rounds_out_and_merges():
    im = _sheet([(3, 3, 4, 4), (9, 9, 4, 4), (20, 3, 6, 6)], size=(48, 32))
    assert P.detect_boxes(im, snap_grid=True, min_px=1)["boxes"] == [[0, 0, 16, 16], [16, 0, 16, 16]]


def test_grid_mode_lists_non_empty_cells():
    im = _sheet([(1, 1, 2, 2), (40, 20, 3, 3)], size=(48, 32))
    assert P.detect_boxes(im, mode="grid")["boxes"] == [[0, 0, 16, 16], [32, 16, 16, 16]]


def test_opaque_sheet_uses_corner_colour_as_background():
    im = _sheet([(5, 5, 8, 8)], size=(32, 32), bg=(255, 0, 255, 255))
    r = P.detect_boxes(im)
    assert r["bg"] == [255, 0, 255]
    assert r["boxes"] == [[5, 5, 8, 8]]


def test_faint_alpha_is_ignored():
    im = _sheet([(5, 5, 8, 8)], size=(32, 32))
    im.putpixel((25, 25), (0, 0, 0, 3))
    assert P.detect_boxes(im, min_px=1)["boxes"] == [[5, 5, 8, 8]]


def test_region_cuts_only_inside_and_keeps_sheet_coordinates():
    im = _sheet([(2, 2, 6, 6), (20, 4, 6, 6), (40, 4, 6, 6)])
    assert P.detect_boxes(im, region=(16, 0, 32, 16))["boxes"] == [[20, 4, 6, 6], [40, 4, 6, 6]]
    # grid cells start at the region's corner
    assert P.detect_boxes(im, mode="grid", cell=8, region=(16, 2, 16, 8))["boxes"] == [[16, 2, 8, 8], [24, 2, 8, 8]]


def test_region_still_judges_background_on_the_whole_sheet():
    im = _sheet([(4, 4, 8, 8)], size=(32, 32))
    r = P.detect_boxes(im, region=(4, 4, 8, 8))  # fully opaque inside, but the sheet has transparency
    assert r["bg"] is None and r["boxes"] == [[4, 4, 8, 8]]
