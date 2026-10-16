"""Room-game UI icons (pixel art in place of emoji), built by `preprocess.py ui` next to theme.css.

Reads data/ui_icons.json and writes
  client/public/media/ui/icons.png   every icon centred in its own cell×cell slot (8 per row)
and returns the CSS (.icon at the theme scale, .icon.x2 twice that, + .icon-<name>) that cmd_ui appends to media/theme.css.

A source is either `sheet` + x, y (+ w, h; default one cell) in assets/, or `key`: a slice already packed into
gen/interiors.json or gen/map.json (run `build` first), optionally shrunk by an integer `down`. The crop is trimmed
to its pixels and must then fit the cell. Rules and the emoji → icon table: docs/conventions/icons.md.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

import config as C

COLS = 8


def _atlas_crop(key: str) -> Image.Image:
    for name in ("interiors", "map"):
        js = C.OUT_DIR / f"{name}.json"
        if not js.exists():
            continue
        f = json.loads(js.read_text(encoding="utf-8"))["frames"].get(key)
        if f:
            r = f["frame"]
            return Image.open(C.OUT_DIR / f"{name}.png").convert("RGBA").crop((r["x"], r["y"], r["x"] + r["w"], r["y"] + r["h"]))
    raise SystemExit(f"icon key '{key}' not in gen/interiors.json or gen/map.json (run build first)")


def _source(name: str, spec: dict, cell: int) -> Image.Image:
    if "key" in spec:
        im = _atlas_crop(spec["key"])
    else:
        src = C.ASSETS_ROOT / spec["sheet"]
        if not src.exists():
            raise SystemExit(f"icon '{name}': {src} not found")
        x, y = spec["x"], spec["y"]
        im = Image.open(src).convert("RGBA").crop((x, y, x + spec.get("w", cell), y + spec.get("h", cell)))
    down = int(spec.get("down", 1))
    if down > 1:
        im = im.resize((im.width // down, im.height // down), Image.NEAREST)
    bb = im.getbbox()
    if not bb:
        raise SystemExit(f"icon '{name}': the crop is empty")
    im = im.crop(bb)
    if im.width > cell or im.height > cell:
        raise SystemExit(f"icon '{name}': {im.width}×{im.height} does not fit the {cell}px cell (use down)")
    return im


def build(path: Path, out_dir: Path, scale: int) -> list[str]:
    """Write icons.png into out_dir; return the CSS lines (empty when there is no icon file). Icons are drawn at the
    theme's `scale` like the frames; negative margins keep a 2× icon from stretching a line of text."""
    if not path.exists():
        return []
    spec = json.loads(path.read_text(encoding="utf-8"))
    cell = int(spec.get("cell", 16))
    icons = spec.get("icons", {})
    if not icons:
        return []
    cols = min(COLS, len(icons))
    rows = (len(icons) + cols - 1) // cols
    sprite = Image.new("RGBA", (cols * cell, rows * cell), (0, 0, 0, 0))
    css = []
    for i, (name, src) in enumerate(icons.items()):
        im = _source(name, src, cell)
        sx, sy = (i % cols) * cell, (i // cols) * cell
        sprite.alpha_composite(im, (sx + (cell - im.width) // 2, sy + (cell - im.height) // 2))
        # percentage positions + a background-size relative to the element: .icon.x2 shows the same cell at 2×
        px = 100 * sx / (sprite.width - cell) if cols > 1 else 0
        py = 100 * sy / (sprite.height - cell) if rows > 1 else 0
        css.append(f".icon-{name} {{ background-position: {px:.4f}% {py:.4f}%; }}")
    sprite.save(out_dir / "icons.png", optimize=True)
    size = cell * scale
    head = [
        f".icon {{ display: inline-block; width: {size}px; height: {size}px; vertical-align: middle; flex: 0 0 auto;"
        f" margin: -{size // 4}px -{size // 8}px; background: url(/media/ui/icons.png) no-repeat;"
        f" background-size: {cols * 100}% {rows * 100}%; image-rendering: pixelated; }}",
        f".icon.x2 {{ width: {size * 2}px; height: {size * 2}px; margin: -{size // 2}px -{size // 4}px; }}",
    ]
    print(f"{len(icons)} icons → media/ui/icons.png")
    return head + css
