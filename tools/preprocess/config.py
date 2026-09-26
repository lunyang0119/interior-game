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
# assets/graphic is split by purpose: Interior/ (rooms, furniture, characters), Map/ (overworld
# tiles, dock backdrop), GUI/ (frames, icons).
INTERIOR = ASSETS / "Interior"
MAP = ASSETS / "Map"
GUI = ASSETS / "GUI"
# Free starter pack. It is no longer on disk; its slices are frozen from the previous atlas (see
# preprocess.load_frozen). Drop the pack back here to re-cut them from source.
FREE = INTERIOR / "Modern tiles_Free"
FULL = INTERIOR / "moderninteriors-win"

OUT_DIR = REPO_ROOT / "client" / "public" / "gen"
MEDIA_DIR = REPO_ROOT / "client" / "public" / "media"
SLICES_FILE = Path(__file__).with_name("slices.json")
MAP_SLICES_FILE = Path(__file__).with_name("map_slices.json")
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
    "kitchen": INTERIOR / "Kitchen and more tileset [16x16]" / "tileset.png",
    "paintings": INTERIOR / "Paintings" / "Paintings_1.png",
    "pi_beds_br": INTERIOR / "pixelinterior" / "beds_BR.png",
    "pi_cabinets_ba": INTERIOR / "pixelinterior" / "cabinets_BA.png",
    "pi_cabinets_lrk": INTERIOR / "pixelinterior" / "cabinets_LRK.png",
    "pi_decorations_br": INTERIOR / "pixelinterior" / "decorations_BR.png",
    "pi_decorations_lrk": INTERIOR / "pixelinterior" / "decorations_LRK.png",
    "pi_doorswindowsstairs_lrk": INTERIOR / "pixelinterior" / "doorswindowsstairs_LRK.png",
    "pi_fixtures_ba": INTERIOR / "pixelinterior" / "fixtures_BA.png",
    "pi_floorswalls_lrk": INTERIOR / "pixelinterior" / "floorswalls_LRK.png",
    "pi_kitchen_lrk": INTERIOR / "pixelinterior" / "kitchen_LRK.png",
    "pi_livingroom_lrk": INTERIOR / "pixelinterior" / "livingroom_LRK.png",
    "pi_textiles_ba": INTERIOR / "pixelinterior" / "textiles_BA.png",
    "pi_wardrobes_br": INTERIOR / "pixelinterior" / "wardrobes_BR.png",
    "floors_walls02": INTERIOR / "floors-walls02.png",
    "furniture03": INTERIOR / "furniture03.png",
    "interior_tiles_lite": INTERIOR / "InteriorTilesLITE.png",
    "small_items02": INTERIOR / "small-items02.png",
    "topdown_doors_windows": INTERIOR / "Top-Down_Retro_Interior" / "TopDownHouse_DoorsAndWindows.png",
    "topdown_floors_walls": INTERIOR / "Top-Down_Retro_Interior" / "TopDownHouse_FloorsAndWalls.png",
    "topdown_floors_walls_open": INTERIOR / "Top-Down_Retro_Interior" / "TopDownHouse_FloorsAndWalls_OpenDoors.png",
    "topdown_furniture1": INTERIOR / "Top-Down_Retro_Interior" / "TopDownHouse_FurnitureState1.png",
    "topdown_furniture2": INTERIOR / "Top-Down_Retro_Interior" / "TopDownHouse_FurnitureState2.png",
    "topdown_small_items": INTERIOR / "Top-Down_Retro_Interior" / "TopDownHouse_SmallItems.png",
    "freepixel": INTERIOR / "FreePixel.png",
    "furnipixel_free": INTERIOR / "furnipixel-free.png",
    "spritesheet_misc": INTERIOR / "spritesheet.png",
    "tiles_and_items": INTERIOR / "tiles and items.png",
    "axulart_all": INTERIOR / "AxulArt・_Basic-Top-down-interior_ALL_By_AxulArt.png",
    "axulart_basic": INTERIOR / "AxulArt・_Basic-Top-down-interior_By_AxulArt.png",
    "walls_and_floors": INTERIOR / "Walls and floors.png",
    "free_modern_pack": INTERIOR / "Free Modern Pack ( Dev Essentials ).png",
    "medieval_pack": INTERIOR / "Medieval Free Pack ( Dev Essentials ).png",
    "interior_no_shadow": INTERIOR / "Interior without swadows.png",
}

# Overworld map sheets (`scan --map`, packed into gen/map.png by `build`). Keys must not contain
# the word "sheet": /api/catalog output is checked for it in the server tests.
_SPROUT = MAP / "Sprout Lands - Sprites - Basic pack"
MAP_SHEETS = {
    "sprout_grass": _SPROUT / "Tilesets" / "Grass.png",
    "sprout_water": _SPROUT / "Tilesets" / "Water.png",
    "sprout_hills": _SPROUT / "Tilesets" / "Hills.png",
    "sprout_dirt": _SPROUT / "Tilesets" / "Tilled_Dirt.png",
    "sprout_paths": _SPROUT / "Objects" / "Paths.png",
    "sprout_bridge": _SPROUT / "Objects" / "Wood_Bridge.png",
    "sprout_fences": _SPROUT / "Tilesets" / "Fences.png",
    "sprout_grass_things": _SPROUT / "Objects" / "Basic_Grass_Biom_things.png",
    "sprout_plants": _SPROUT / "Objects" / "Basic_Plants.png",
    "houses": ASSETS / "Houses.png",
    "plains": MAP / "Pixel Plains Free Pack" / "All free tiles.png",
    "nature_trees": MAP / "Nature_MP" / "Nature_MP_Trees.png",
    "nature_rocks": MAP / "Nature_MP" / "Nature_MP_Rocks.png",
}
MAP_ICONS_DIR = GUI / "Map Legend Icons" / "Icons"   # 16x24 marker icons, referenced as `file` slices
DOCK_DIR = MAP / "Dock"                              # 0.png .. 8.png, 384x216 parallax layers (back → front)

# Character frames. Every variant yields one horizontal sheet of ANIM_STRIPS
# concatenated in order; each strip is FRAMES_PER_DIR * len(DIRS) frames.
FRAME_W, FRAME_H = 16, 32
DIRS = ["right", "up", "left", "down"]  # order inside each 24-frame LimeZu strip
FRAMES_PER_DIR = 6
ANIM_STRIPS = ["run", "idle"]  # concatenated in this order → 48 frames total

# Character Generator sheets (896x656): 32px rows; row 1 = idle anim, row 2 = run.
GEN_DIR = FULL / "2_Characters" / "Character_Generator"
CUSTOM_DIR = ASSETS_ROOT / "custom"  # assets/custom/Hairstyles/Hairstyle_30_01.png etc.
GEN_ROWS = {"idle": 1, "run": 2}

_STYLE_COLOR = re.compile(r"_(\d+)(?:_[A-Za-z_]+?)?_(\d+)\.png$")  # Outfit_03_02 / Accessory_04_Snapback_02
_STYLE_ONLY = re.compile(r"_(\d+)\.png$")                          # Body_05 / Eyes_02


def _gen_layer(folder: str, prefix: str, none: bool = False, none_first: bool = False) -> list[dict]:
    """All 16x16 sheets of one generator layer as variants, sorted by (style, color).

    Variant: {"name", "sheet", "style", "color"}. When `none` is True, the LAST index is a
    fully transparent "nothing" variant (hair/accessory can be absent) — index 0 stays a real
    style so fresh avatars are not bald.
    """
    # pack folder + your own additions in assets/custom/<folder>/ (same 896x656 layout, same naming)
    dirs = [GEN_DIR / folder / "16x16", CUSTOM_DIR / folder]
    out: list[dict] = []
    for d in dirs:
        if not d.exists():
            continue
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
