"""Source asset mapping for the preprocess tool.

Paths are relative to the repo root. Raw assets live in assets/ (gitignored).
When the full Modern Interiors pack (with Character Generator) arrives, add its
layer folders to CHAR_LAYERS below; nothing else should need to change.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSETS = REPO_ROOT / "assets" / "graphic"
FREE = ASSETS / "Modern tiles_Free"

OUT_DIR = REPO_ROOT / "client" / "public" / "gen"
SLICES_FILE = Path(__file__).with_name("slices.json")
CONTACT_SHEET = Path(__file__).with_name("contact_sheet.png")
ITEMS_FILE = REPO_ROOT / "data" / "items.json"

CELL = 16

# Interior sheets that `scan` can slice and `build` packs into the atlas.
SHEETS = {
    "interiors": FREE / "Interiors_free" / "16x16" / "Interiors_free_16x16.png",
    "room_builder": FREE / "Interiors_free" / "16x16" / "Room_Builder_free_16x16.png",
    "kitchen": ASSETS / "Kitchen and more tileset [16x16]" / "tileset.png",
}

# Character frames. Each variant lists animation strips in the order they are
# concatenated into one horizontal sheet. All strips share FRAME_W x FRAME_H.
FRAME_W, FRAME_H = 16, 32
DIRS = ["right", "up", "left", "down"]  # order inside each 24-frame LimeZu strip
FRAMES_PER_DIR = 6
ANIM_STRIPS = ["run", "idle"]  # concatenated in this order → 48 frames total

CHARS_DIR = FREE / "Characters_free"


def _free_char(name: str) -> dict:
    return {
        "name": name.lower(),
        "run": CHARS_DIR / f"{name}_run_16x16.png",
        "idle": CHARS_DIR / f"{name}_idle_anim_16x16.png",
    }


# layer -> list of variants (index = value stored in avatars table).
# Layers with an empty list are exposed in manifest with count 0 so the editor hides them.
CHAR_LAYERS = {
    "skin": [_free_char(n) for n in ("Adam", "Alex", "Amelia", "Bob")],
    "hair": [],
    "hair_color": [],
    "outfit": [],
    "acc": [],
}

# Draw order of layers inside the avatar container (bottom → top).
LAYER_ORDER = ["skin", "outfit", "hair", "acc"]
