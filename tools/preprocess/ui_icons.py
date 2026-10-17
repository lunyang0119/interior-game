"""Room-game UI icons (pixel art in place of emoji), built by `preprocess.py ui` next to theme.css.

Reads data/ui_icons.json and writes
  client/public/media/ui/icons.png   every icon centred in its own slot, already at screen size (8 per row)
and returns the CSS (.icon, .icon.x2 twice that, + .icon-<name>) that cmd_ui appends to media/theme.css.

A source is `sheet` + x, y (+ w, h; default one cell) in assets/, `gen` + x, y, w, h in client/public/gen/, `key`: a
slice packed into gen/interiors.json or gen/map.json (run `build` first), or `svg`: a pixel-grid SVG in assets/ made
of axis-aligned <polygon>s (filled with `color`, one source pixel per grid unit). An integer `down` shrinks the source.
The crop is trimmed to its pixels and drawn at `px` screen pixels per source pixel (default: the theme scale, like the
frames; a finer source such as a 24-grid SVG uses 1), and must then fit the cell × scale slot.
Rules and the emoji → icon table: docs/conventions/icons.md.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from PIL import Image, ImageDraw

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


def _svg(src: Path, color: str) -> Image.Image:
    """Rasterise a pixel-grid SVG (integer <polygon> points on its viewBox grid): a grid cell is filled when the
    polygons cover its centre."""
    text = src.read_text(encoding="utf-8")
    vb = [int(float(v)) for v in re.search(r'viewBox="([^"]+)"', text).group(1).split()]
    k = 8  # supersampling: polygon edges lie on grid lines, so sampling each cell's centre is exact
    mask = Image.new("L", (vb[2] * k, vb[3] * k), 0)
    d = ImageDraw.Draw(mask)
    for pts in re.findall(r'<polygon[^>]*points="([^"]+)"', text):
        v = [float(n) for n in pts.replace(",", " ").split()]
        d.polygon([((v[i] - vb[0]) * k, (v[i + 1] - vb[1]) * k) for i in range(0, len(v), 2)], fill=255)
    small = Image.new("L", (vb[2], vb[3]), 0)
    for y in range(vb[3]):
        for x in range(vb[2]):
            small.putpixel((x, y), mask.getpixel((x * k + k // 2, y * k + k // 2)))
    im = Image.new("RGBA", small.size, color)
    im.putalpha(small)
    return im


def _source(name: str, spec: dict, cell: int) -> Image.Image:
    if "svg" in spec:
        src = C.ASSETS_ROOT / spec["svg"]
        if not src.exists():
            raise SystemExit(f"icon '{name}': {src} not found")
        im = _svg(src, spec.get("color", "#000000"))
    elif "key" in spec:
        im = _atlas_crop(spec["key"])
    elif "gen" in spec:  # a frame of another generated strip, e.g. the inn cat (gen/cat/<variant>.png)
        src = C.OUT_DIR / spec["gen"]
        if not src.exists():
            raise SystemExit(f"icon '{name}': {src} not found (run build first)")
        x, y = spec["x"], spec["y"]
        im = Image.open(src).convert("RGBA").crop((x, y, x + spec.get("w", cell), y + spec.get("h", cell)))
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
    return im.crop(bb)


def build(path: Path, out_dir: Path, scale: int) -> list[str]:
    """Write icons.png into out_dir; return the CSS lines (empty when there is no icon file). Negative margins keep
    the cell × scale box from stretching a line of text."""
    if not path.exists():
        return []
    spec = json.loads(path.read_text(encoding="utf-8"))
    cell = int(spec.get("cell", 16))
    icons = spec.get("icons", {})
    if not icons:
        return []
    cols = min(COLS, len(icons))
    rows = (len(icons) + cols - 1) // cols
    size = cell * scale  # one slot of the sprite = one .icon box, in screen pixels
    sprite = Image.new("RGBA", (cols * size, rows * size), (0, 0, 0, 0))
    css = []
    for i, (name, src) in enumerate(icons.items()):
        im = _source(name, src, cell)
        k = int(src.get("px", scale))
        im = im.resize((im.width * k, im.height * k), Image.NEAREST)
        if im.width > size or im.height > size:
            raise SystemExit(f"icon '{name}': {im.width}×{im.height} screen px does not fit the {size}px slot (use down or px)")
        sx, sy = (i % cols) * size, (i // cols) * size
        sprite.alpha_composite(im, (sx + (size - im.width) // 2, sy + (size - im.height) // 2))
        # percentage positions + a background-size relative to the element: .icon.x2 shows the same slot at 2×
        px = 100 * sx / (sprite.width - size) if cols > 1 else 0
        py = 100 * sy / (sprite.height - size) if rows > 1 else 0
        css.append(f".icon-{name} {{ background-position: {px:.4f}% {py:.4f}%; }}")
    sprite.save(out_dir / "icons.png", optimize=True)
    head = [
        f".icon {{ display: inline-block; width: {size}px; height: {size}px; vertical-align: middle; flex: 0 0 auto;"
        f" margin: -{size // 4}px -{size // 8}px; background: url(/media/ui/icons.png) no-repeat;"
        f" background-size: {cols * 100}% {rows * 100}%; image-rendering: pixelated; }}",
        f".icon.x2 {{ width: {size * 2}px; height: {size * 2}px; margin: -{size // 2}px -{size // 4}px; }}",
    ]
    print(f"{len(icons)} icons → media/ui/icons.png")
    return head + css
