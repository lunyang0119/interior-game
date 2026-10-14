"""Train (/train/) page UI from the cyberpunk GUI pack: `preprocess.py train-ui`.

Reads assets/graphic/GUI/cyberpunk GUI/{status_button,activity_box,alert,icon}.png and writes
  client/public/media/train/status_button.png   status chips + buttons   (9-slice)
  client/public/media/train/activity_box.png    the foldable action bars (9-slice)
  client/public/media/train/alert.png           toasts                   (9-slice)
  client/public/media/train/icons.png           icon sprite (fixed cells)
  client/src/train/cyber.css                    the train page's frame variables + .ic-<name> classes (tracked)

The frames arrive with transparent margins and are not sliced: each is cropped to its drawing and gets hand-set
9-slice borders (SLICES, in source pixels) so the corners and the decorative columns never stretch. The icon
sheet is a 15×3 grid; every icon is cut by its own pixels and re-packed into equal cells, named in ICON_NAMES.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

import config as C

SRC = C.REPO_ROOT / "assets" / "graphic" / "GUI" / "cyberpunk GUI"
OUT = C.MEDIA_DIR / "train"
CSS_OUT = C.REPO_ROOT / "client" / "src" / "train" / "cyber.css"

# 9-slice borders in source pixels: (top, right, bottom, left). Drawn at SCALE× in CSS.
SLICES = {
    "status_button": (10, 12, 5, 5),   # cut corner at the top right
    "activity_box": (10, 12, 6, 12),    # decorative column on the left, cut corner (10 px tall) on the right
    "alert": (12, 12, 12, 12),          # bracket corners + the thick top rail
}
# CSS pixels per source pixel. Chips/buttons/toasts stay 1× (a 2× frame makes every chip ~56 px tall on a phone);
# the action bar is big anyway, so its decorative column gets the crisp 2×.
SCALE = {"status_button": 1, "activity_box": 2, "alert": 1}

# icon sheet grid (sheet is 546×128: 15 columns, 3 rows)
GRID_COLS, GRID_ROWS = 15, 3
GRID_X0, GRID_Y0, GRID_W, GRID_H = 2, 6, 36.4, 37
CELL = 28  # packed cell size (icons are ≤ 26 px)
ICON_PX = 39  # default on-screen size of a .ic (panel titles); chips/buttons set their own in style.css
ICON_NAMES = [
    None, None, "menu", "globe", "chat", "share", "power", "arrow_right", "arrow_left", "arrow_up", "arrow_down", "clock", "crown", "target", "pin",
    "expand", "trophy", "search", "minus", "plus", "chart", "camera", "move", "speaker", "mute", "mail", "play", "play_back", "tri_up", "tri_down",
    "close", "help", "gear", "home", "exit", "heart", "signal", "alert", "sliders", "cart", "trash", "save", "gamepad", "pause", "play_small",
]


def crop_frame(im: Image.Image) -> Image.Image:
    """Crop to the drawing, ignoring stray single pixels (alert.png has one above its rail)."""
    a = im.getchannel("A")
    w, h = im.size
    rows = [y for y in range(h) if sum(1 for x in range(w) if a.getpixel((x, y)) > 0) >= 4]
    cols = [x for x in range(w) if sum(1 for y in range(h) if a.getpixel((x, y)) > 0) >= 4]
    return im.crop((cols[0], rows[0], cols[-1] + 1, rows[-1] + 1))


def cut_icons(sheet: Image.Image) -> tuple[Image.Image, dict[str, list[int]]]:
    """Each grid cell → the bbox of its pixels → centred into a CELL×CELL slot of the sprite."""
    names = [n for n in ICON_NAMES if n]
    cols = 8
    rows = (len(names) + cols - 1) // cols
    sprite = Image.new("RGBA", (cols * CELL, rows * CELL), (0, 0, 0, 0))
    table: dict[str, list[int]] = {}
    k = 0
    for i, name in enumerate(ICON_NAMES):
        if not name:
            continue
        r, c = divmod(i, GRID_COLS)
        x0 = int(round(GRID_X0 + c * GRID_W)); y0 = int(round(GRID_Y0 + r * GRID_H))
        cell = sheet.crop((x0, y0, min(sheet.width, int(round(x0 + GRID_W))), min(sheet.height, y0 + GRID_H)))
        bb = cell.getbbox()
        if not bb:
            continue
        icon = cell.crop(bb)
        sx, sy = (k % cols) * CELL, (k // cols) * CELL
        ox, oy = sx + (CELL - icon.width) // 2, sy + (CELL - icon.height) // 2
        sprite.alpha_composite(icon, (ox, oy))
        table[name] = [sx, sy]
        k += 1
    return sprite, table


def build() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    sizes: dict[str, tuple[int, int]] = {}
    for name in SLICES:
        im = Image.open(SRC / f"{name}.png").convert("RGBA")
        c = crop_frame(im)
        c.save(OUT / f"{name}.png")
        sizes[name] = c.size
    sprite, table = cut_icons(Image.open(SRC / "icon.png").convert("RGBA"))
    sprite.save(OUT / "icons.png")
    (OUT / "icons.json").write_text(json.dumps(table), encoding="utf-8")
    CSS_OUT.write_text(render_css(sizes, sprite.size, table), encoding="utf-8")
    print(f"train-ui: {len(SLICES)} frames + {len(table)} icons → {OUT}, {CSS_OUT.relative_to(C.REPO_ROOT)}")


def render_css(sizes: dict[str, tuple[int, int]], sprite_size: tuple[int, int], icons: dict[str, list[int]]) -> str:
    def frame(name: str, var: str) -> str:
        # style.css uses `border: var(--slice-X-px) solid …` (one width), so that variable stays single-valued and the
        # real four-sided width goes into --slice-X-px4, applied below with border-width
        t, r, b, l = SLICES[name]
        k = SCALE[name]
        return (f"  --frame-{var}: url(/media/train/{name}.png); --slice-{var}: {t} {r} {b} {l}; "
                f"--slice-{var}-px: {max(t, r, b, l) * k}px; --slice-{var}-px4: {t * k}px {r * k}px {b * k}px {l * k}px; "
                f"--pad-{var}: 4px;\n")

    out = ["/* GENERATED by `python tools/preprocess/preprocess.py train-ui` from assets/graphic/GUI/cyberpunk GUI. Do not edit. */",
           "/* Train page only (<html class=\"train\">): html.train:root outranks theme.css's html:root, so these frames and",
           "   colours replace the room game's theme there. */",
           "html.train:root {",
           "  --bg: #0b0f1e; --panel: #0e1530; --chip: #0a1024; --card: #131b3a; --text: #e8f6ff; --muted: #7f9bb8; --primary: #37d6e6; --danger: #ff6b6b;",
           "  --frame-panel: none; --slice-panel: 0; --slice-panel-px: 0px; --pad-panel: 12px;",
           "  --frame-ctx: none; --slice-ctx: 0; --slice-ctx-px: 0px; --frame-input: none; --slice-input: 0; --slice-input-px: 0px;"]
    out.append(frame("status_button", "button").rstrip("\n"))
    out.append(frame("status_button", "button-primary").rstrip("\n"))
    out.append(frame("status_button", "chip").rstrip("\n"))
    out.append(frame("alert", "toast").rstrip("\n"))
    t, r, b, l = SLICES["activity_box"]
    k = SCALE["activity_box"]
    out.append(f"  --frame-bar: url(/media/train/activity_box.png); --slice-bar: {t} {r} {b} {l}; "
               f"--slice-bar-px: {t * k}px {r * k}px {b * k}px {l * k}px;")
    out.append("  --cyber-ink: #060a1a; --cyber-cyan: #37d6e6; --cyber-text: #e8f6ff;")
    out.append("}")
    out.append("")
    out.append("/* framed elements: the frame carries its own fill, so no CSS background underneath (the cut corners stay transparent) */")
    out.append("button, .chip { background: transparent; border-radius: 0; color: var(--cyber-text); border-width: var(--slice-button-px4); }")
    out.append(".chip { border-width: var(--slice-chip-px4); }")
    out.append("button.primary { background: transparent; color: var(--cyber-cyan); font-weight: 700; border-width: var(--slice-button-primary-px4); }")
    out.append("button.danger { background: transparent; color: #ff7a7a; }")
    out.append("button.close { border: 0; border-image: none; }")
    out.append("button:disabled { opacity: 0.45; }")
    out.append("/* theme.css strips the panel background for its own frame; the train page has no panel frame, so paint it */")
    out.append("html.train .panel { background: var(--panel); border-radius: 12px; box-shadow: 0 8px 30px rgba(0,0,0,.6); border: 1px solid var(--cyber-cyan); }")
    out.append("html.train .panel-head .close { color: var(--cyber-cyan); }")
    out.append(".bar { background: transparent; backdrop-filter: none; border-radius: 0; image-rendering: pixelated;"
               " border-style: solid; border-color: transparent; border-width: var(--slice-bar-px); border-image: var(--frame-bar) var(--slice-bar) fill round;"
               " padding: 4px 6px 4px 8px; }")
    out.append("#toast { background: transparent; border-radius: 0; color: var(--cyber-text); border-width: var(--slice-toast-px4); padding: 6px 10px; }")
    out.append("")
    out.append("/* icon sprite */")
    w, h = sprite_size
    # percentage positions + a background-size relative to the element: the icon can be shown at any size
    cols, rows = w // CELL, h // CELL
    out.append(f".ic {{ display: inline-block; width: {ICON_PX}px; height: {ICON_PX}px; vertical-align: middle; background: url(/media/train/icons.png) no-repeat;"
               f" background-size: {cols * 100}% {rows * 100}%; image-rendering: pixelated; flex: 0 0 auto; }}")
    out.append(".ic + span, span + .ic { margin-left: 4px; }")
    for name, (x, y) in icons.items():
        px = 100 * x / (w - CELL) if w > CELL else 0
        py = 100 * y / (h - CELL) if h > CELL else 0
        out.append(f".ic-{name} {{ background-position: {px:.4f}% {py:.4f}%; }}")
    out.append("")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    build()
