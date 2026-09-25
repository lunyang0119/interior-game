"""Source asset mapping for the preprocess tool.

Paths are relative to the repo root. Raw assets live in assets/ (gitignored).
Character layers come from the full Modern Interiors pack's Character Generator
folders (per-layer 896x656 sheets); furniture slices still come from the sheets
in SHEETS plus optional single-object PNGs referenced by `file` in slices.json.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSETS_ROOT = REPO_ROOT / "assets"
ASSETS = ASSETS_ROOT / "graphic"
FREE = ASSETS / "Modern tiles_Free"
FULL = ASSETS / "moderninteriors-win"

OUT_DIR = REPO_ROOT / "client" / "public" / "gen"
MEDIA_DIR = REPO_ROOT / "client" / "public" / "media"
SLICES_FILE = Path(__file__).with_name("slices.json")
CONTACT_SHEET = Path(__file__).with_name("contact_sheet.png")
ITEMS_FILE = REPO_ROOT / "data" / "items.json"
UI_THEME_FILE = REPO_ROOT / "data" / "ui_theme.json"

BGM_DIR = ASSETS_ROOT / "BGM"          # BGM/day/*.mp3, BGM/night/*.mp3
FONTS_DIR = ASSETS_ROOT / "fonts"      # *.ttf

CELL = 16

# Interior sheets that `scan` can slice and `build` packs into the atlas.
SHEETS = {
    "interiors": FREE / "Interiors_free" / "16x16" / "Interiors_free_16x16.png",
    "room_builder": FREE / "Interiors_free" / "16x16" / "Room_Builder_free_16x16.png",
    "kitchen": ASSETS / "Kitchen and more tileset [16x16]" / "tileset.png",
    "paintings": ASSETS / "Paintings" / "Paintings_1.png",
}

# Character frames. Every variant yields one horizontal sheet of ANIM_STRIPS
# concatenated in order; each strip is FRAMES_PER_DIR * len(DIRS) frames.
FRAME_W, FRAME_H = 16, 32
DIRS = ["right", "up", "left", "down"]  # order inside each 24-frame LimeZu strip
FRAMES_PER_DIR = 6
ANIM_STRIPS = ["run", "idle"]  # concatenated in this order → 48 frames total

# Character Generator sheets (896x656): 32px rows; row 1 = idle anim, row 2 = run.
GEN_DIR = FULL / "2_Characters" / "Character_Generator"
GEN_ROWS = {"idle": 1, "run": 2}

_STYLE_COLOR = re.compile(r"_(\d+)(?:_[A-Za-z_]+?)?_(\d+)\.png$")  # Outfit_03_02 / Accessory_04_Snapback_02
_STYLE_ONLY = re.compile(r"_(\d+)\.png$")                          # Body_05 / Eyes_02


def _gen_layer(folder: str, prefix: str, none: bool = False, none_first: bool = False) -> list[dict]:
    """All 16x16 sheets of one generator layer as variants, sorted by (style, color).

    Variant: {"name", "sheet", "style", "color"}. When `none` is True, the LAST index is a
    fully transparent "nothing" variant (hair/accessory can be absent) — index 0 stays a real
    style so fresh avatars are not bald.
    """
    d = GEN_DIR / folder / "16x16"
    out: list[dict] = []
    if d.exists():
        for p in sorted(d.glob(f"{prefix}_*.png")):
            m = _STYLE_COLOR.search(p.name)
            if m:
                style, color = int(m.group(1)), int(m.group(2))
            else:
                m1 = _STYLE_ONLY.search(p.name)
                style, color = (int(m1.group(1)) if m1 else len(out) + 1), 0
            out.append({"name": p.stem, "sheet": p, "style": style, "color": color})
        out.sort(key=lambda v: (v["style"], v["color"]))
    if none_first:
        out.insert(0, {"name": "none", "sheet": None, "style": 0, "color": 0})
    elif none:
        out.append({"name": "none", "sheet": None, "style": 10_000, "color": 0})
    return out


# Extra hair colours: data/hair_palette.png is the pack's Hairstyles_palette.png (8 columns of 5px:
# 7 hair colours + outline) with more 5px-wide columns painted to the right. Each column holds the
# light / mid / dark shade in rows 0-2 / 3-5 / 6-8. Every hairstyle gets one recoloured variant per extra column.
HAIR_PALETTE_FILE = REPO_ROOT / "data" / "hair_palette.png"
HAIR_BASE_SHADES = ((204, 150, 89), (179, 123, 63), (171, 103, 54))  # colour 01 = light, mid, dark
HAIR_PALETTE_BUILTIN_COLS = 8


def _extra_hair_colors() -> list[tuple[tuple[int, int, int], ...]]:
    if not HAIR_PALETTE_FILE.exists():
        return []
    from PIL import Image
    im = Image.open(HAIR_PALETTE_FILE).convert("RGBA")
    px = im.load()
    out = []
    for x in range(HAIR_PALETTE_BUILTIN_COLS * 5, im.width, 5):
        shades = tuple(px[x, y][:3] for y in (0, 3, 6))
        if all(px[x, y][3] > 0 for y in (0, 3, 6)):
            out.append(shades)
    return out


def _with_extra_hair_colors(variants: list[dict]) -> list[dict]:
    """Append a recoloured copy of each style's colour-01 sheet for every extra palette column."""
    extras = _extra_hair_colors()
    if not extras:
        return variants
    base = [v for v in variants if v.get("color") == 1]
    for k, shades in enumerate(extras):
        color = HAIR_PALETTE_BUILTIN_COLS + k  # 8, 9, ...
        for v in base:
            variants.append({"name": f"{v['name'][:-3]}_{color:02d}", "sheet": v["sheet"], "style": v["style"],
                             "color": color, "recolor": dict(zip(HAIR_BASE_SHADES, shades))})
    variants.sort(key=lambda v: (v["style"], v["color"]))
    return variants


# layer -> list of variants (index = value stored in avatars table).
# Layers with an empty list are exposed in manifest with count 0 so the editor hides them.
CHAR_LAYERS = {
    # premade characters: index 0 = none (default). When a preset is chosen it replaces every other layer.
    "preset": _gen_layer("0_Premade_Characters", "Premade_Character", none_first=True),
    "skin": _gen_layer("Bodies", "Body"),
    "eyes": _gen_layer("Eyes", "Eyes"),
    "outfit": _gen_layer("Outfits", "Outfit"),
    "hair": _with_extra_hair_colors(_gen_layer("Hairstyles", "Hairstyle", none=True)),
    "acc": _gen_layer("Accessories", "Accessory", none=True),
}

# Draw order of layers inside the avatar container (bottom → top), per CHARACTER_GENERATOR.txt.
LAYER_ORDER = ["preset", "skin", "eyes", "outfit", "hair", "acc"]
# layers that, when not "none", are drawn alone
EXCLUSIVE_LAYERS = {"preset"}

# Korean labels for the avatar editor (shipped in manifest).
LAYER_LABELS = {"preset": "프리셋 캐릭터", "skin": "몸", "eyes": "눈", "outfit": "옷", "hair": "머리", "acc": "악세서리"}
