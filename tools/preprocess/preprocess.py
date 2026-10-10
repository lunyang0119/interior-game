"""Preprocess raw LimeZu assets into clean sprite sheets + manifest.json.

Usage (from repo root):
    python tools/preprocess/preprocess.py scan [--sheet interiors] [--min-cells 1] [--map]
        Finds opaque regions on a sheet, snaps them to the 16px grid, and writes
        candidate slices to slices.json (existing named entries are preserved).
        Also renders contact_<sheet>.png with every slice outlined and labelled.
        --map scans a MAP_SHEETS sheet into map_slices.json instead.

    python tools/preprocess/preprocess.py build [--allow-shrink]
        Packs every slice in slices.json into client/public/gen/interiors.png +
        interiors.json (Phaser atlas), builds per-layer character sheets under
        client/public/gen/chars/<layer>/<n>.png, packs map_slices.json into
        gen/map.png + map.json, copies the dock backdrop to gen/dock/, cuts the
        inn cat (config.CAT_VARIANT) into gen/cat/<variant>.png and writes manifest.json.
        Slices whose source sheet/file is missing are copied ("frozen") from the
        previous atlas so a pack that went away does not lose items.
        The build refuses to shrink a character layer (that would shift avatar
        indices stored in the DB) unless --allow-shrink is given.

    python tools/preprocess/preprocess.py scaffold
        Adds a placeholder items.json entry for every atlas key that has none.

    python tools/preprocess/preprocess.py media
        Copies BGM (assets/bgm/{day,night}/*.mp3 = default lists; assets/bgm/<place>/[day|night/]*.mp3
        = per-place lists, e.g. dock/; legacy/ is skipped), fonts (assets/fonts/*.ttf) and
        sound effects (assets/sfx/**/<kind>_*.mp3 → media/sfx/<kind>.mp3) into
        client/public/media/ with ASCII names and writes media/bgm.json + media/sfx.json.

    python tools/preprocess/preprocess.py ui
        Reads data/ui_theme.json, cuts the 9-slice frame PNGs into
        client/public/media/ui/ and writes client/public/media/theme.css.

    python tools/preprocess/preprocess.py editor
        Opens the browser slice/item editor (see editor.py).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import deque
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
import config as C  # noqa: E402

TILE_PREFIX = "tile_"  # slices with this prefix are room tiles, not shop items
# Per-slice tile metadata (optional keys on a slice): "step" = footstep sound kind on that tile,
# "walk": false = avatars cannot enter the cell. Copied into manifest keys by atlas_keys().
TILE_STEPS = ("wood", "tile", "grass", "water", "none")


# ----------------------------------------------------------------------------
# slices.json helpers
# ----------------------------------------------------------------------------

def load_slices(path: Path | None = None) -> list[dict]:
    path = path or C.SLICES_FILE
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return []


def save_slices(slices: list[dict], path: Path | None = None) -> None:
    path = path or C.SLICES_FILE
    slices.sort(key=lambda s: (s.get("sheet", "~file"), s.get("y", 0), s.get("x", 0), s["key"]))
    path.write_text(json.dumps(slices, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


# ----------------------------------------------------------------------------
# frozen atlas: fallback for slices whose source is gone
# ----------------------------------------------------------------------------

# keys that the current build had to copy from the previous atlas (reset by pack_atlas)
FROZEN_USED: list[str] = []


def load_frozen(json_path: Path, png_path: Path) -> tuple[Image.Image, dict] | None:
    """The previously built atlas, fully loaded into memory so the build can overwrite the files.
    Returns (image, frames) or None when there is no previous atlas."""
    if not json_path.exists() or not png_path.exists():
        return None
    frames = json.loads(json_path.read_text(encoding="utf-8")).get("frames", {})
    with Image.open(png_path) as im:
        image = im.convert("RGBA")
        image.load()
    return image, frames


def _frozen_crop(key: str, frozen: tuple[Image.Image, dict] | None) -> Image.Image | None:
    if frozen is None or key not in frozen[1]:
        return None
    f = frozen[1][key]["frame"]
    return frozen[0].crop((f["x"], f["y"], f["x"] + f["w"], f["y"] + f["h"]))


def slice_rect(s: dict) -> tuple[int, int, int, int]:
    return s["x"], s["y"], s["w"], s["h"]


class SourceMissing(Exception):
    """The sheet or file a slice points at is not on disk."""


class SheetStore:
    """name → RGBA image, opened on first use (the discovered sheet list is long; only touched ones load)."""

    def __init__(self, paths: dict[str, Path]):
        self.paths = paths
        self.cache: dict[str, Image.Image] = {}

    def __contains__(self, name: object) -> bool:
        return name in self.paths and self.paths[name].exists()

    def __getitem__(self, name: str) -> Image.Image:
        if name not in self.cache:
            self.cache[name] = Image.open(self.paths[name]).convert("RGBA")
        return self.cache[name]


def _slice_from_source(s: dict, sheets: dict[str, Image.Image], file_base: Path) -> Image.Image:
    if "file" in s:
        path = file_base / s["file"]
        if not path.exists():
            raise SourceMissing(f"file for slice '{s['key']}' not found: {path}")
        return rescale(Image.open(path).convert("RGBA"), s.get("scale"))
    if "parts" in s:
        crops = [_slice_from_source({"key": s["key"], **part}, sheets, file_base) for part in s["parts"]]
        out = Image.new("RGBA", (max(c.width for c in crops), sum(c.height for c in crops)))
        y = 0
        for c in crops:
            out.paste(c, (0, y))
            y += c.height
        return out
    if s["sheet"] not in sheets:
        raise SourceMissing(f"sheet '{s['sheet']}' for slice '{s['key']}' not found")
    x, y, w, h = slice_rect(s)
    im = sheets[s["sheet"]].crop((x, y, x + w, y + h))
    if s.get("transparent"):
        im = knock_out(im, tuple(s["transparent"]))
    return rescale(im, s.get("scale"))


def rescale(im: Image.Image, scale) -> Image.Image:
    """`scale` on a slice shrinks/enlarges the crop with nearest-neighbour (32px tiles → 0.5 for the 16px grid)."""
    if not scale or float(scale) == 1:
        return im
    f = float(scale)
    return im.resize((max(1, round(im.width * f)), max(1, round(im.height * f))), Image.NEAREST)


SHRUNK_DIR = "_16px"  # assets/graphic/<Root>/_16px/<flattened source path>.png


def is_blocky(im: Image.Image, k: int = 2) -> bool:
    """True when every k×k block is one colour: the image is a k× nearest-neighbour upscale (LimeZu 32x32 = 16x16 ×2)."""
    if im.width % k or im.height % k:
        return False
    px = im.convert("RGBA").load()
    for y in range(0, im.height, k):
        for x in range(0, im.width, k):
            c = px[x, y]
            for dy in range(k):
                for dx in range(k):
                    if px[x + dx, y + dy] != c:
                        return False
    return True


def shrink_image(im: Image.Image, scale: float = 0.5, method: str = "auto") -> tuple[Image.Image, str]:
    """Downscale a sheet for the 16px grid. `nearest` keeps 2×-upscaled art pixel-exact, `box` averages native
    high-res art; `auto` picks nearest when the image is blocky at 1/scale, else box. Returns (image, method used)."""
    im = im.convert("RGBA")
    size = (max(1, round(im.width * scale)), max(1, round(im.height * scale)))
    if method == "auto":
        k = round(1 / scale)
        method = "nearest" if k >= 2 and abs(k * scale - 1) < 1e-9 and is_blocky(im, k) else "box"
    if method == "nearest":
        return im.resize(size, Image.NEAREST), method
    if method == "box":
        # premultiply so transparent pixels do not bleed dark fringes into the average
        pre = Image.new("RGBA", im.size)
        src = im.load()
        dst = pre.load()
        for y in range(im.height):
            for x in range(im.width):
                r, g, b, a = src[x, y]
                dst[x, y] = (r * a // 255, g * a // 255, b * a // 255, a)
        out = pre.resize(size, Image.BOX)
        o = out.load()
        for y in range(out.height):
            for x in range(out.width):
                r, g, b, a = o[x, y]
                if a:
                    o[x, y] = (min(255, r * 255 // a), min(255, g * 255 // a), min(255, b * 255 // a), a)
        return out, method
    raise ValueError(f"unknown method '{method}' (auto | nearest | box)")


def shrunk_path(src: Path, group: str | None = None) -> Path:
    """Where the 16px copy of `src` goes: assets/graphic/<Interior|Map>/_16px/<path flattened with __>.png.
    The root is the sheet's own root under assets/graphic when it has one, else `group` (default Interior)."""
    src = src.resolve()
    try:
        rel = src.relative_to(C.ASSETS.resolve())
        root = rel.parts[0] if rel.parts[0] in C.DISCOVER_ROOTS else (group or "Interior")
        rest = rel.parts[1:] if rel.parts[0] in C.DISCOVER_ROOTS else rel.parts
    except ValueError:
        root, rest = (group or "Interior"), (src.name,)
    flat = "__".join(rest)
    if flat.lower().endswith(".png"):
        flat = flat[:-4]
    return C.ASSETS / root / SHRUNK_DIR / f"{flat}.png"


def shrink_sheet(src: Path, scale: float = 0.5, method: str = "auto", group: str | None = None) -> tuple[Path, str]:
    """Write the downscaled copy of one sheet; the editor and `build` pick it up like any other sheet."""
    out = shrunk_path(src, group)
    out.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        small, used = shrink_image(im, scale, method)
    small.save(out, optimize=True)
    return out, used


def cmd_shrink(args: argparse.Namespace) -> None:
    """32px (or any) sheets → 16px copies under assets/graphic/<Root>/_16px/."""
    paths: list[Path] = []
    for raw in args.paths:
        p = Path(raw)
        if not p.is_absolute():
            p = (C.ASSETS / raw) if (C.ASSETS / raw).exists() else Path.cwd() / raw
        if p.is_dir():
            paths += sorted(q for q in p.rglob("*.png") if SHRUNK_DIR not in q.parts)
        elif p.exists():
            paths.append(p)
        else:
            sys.exit(f"not found: {raw}")
    for p in paths:
        out, used = shrink_sheet(p, args.scale, args.method, args.group)
        print(f"{p.name} → {out.relative_to(C.ASSETS).as_posix()} ({used})")
    print(f"{len(paths)} sheet(s) shrunk")


def knock_out(im: Image.Image, rgb: tuple[int, ...]) -> Image.Image:
    """Make every pixel of exactly this RGB colour transparent (for sheets drawn on a solid backdrop)."""
    im = im.copy()
    px = im.load()
    r, g, b = rgb[:3]
    for y in range(im.height):
        for x in range(im.width):
            if px[x, y][:3] == (r, g, b):
                px[x, y] = (0, 0, 0, 0)
    return im


def slice_image(s: dict, sheets: dict[str, Image.Image], file_base: Path | None = None,
                frozen: tuple[Image.Image, dict] | None = None) -> Image.Image:
    """Crop for a slice: a rect on a named sheet (optionally with `transparent: [r,g,b]`, a backdrop
    colour to knock out), a standalone PNG (`file`, relative to `file_base`, default assets/graphic/Interior),
    or `parts` — rects stacked top-to-bottom (for strips split by transparent separators). When the source is missing and `frozen` (a previous atlas) has the key,
    the old frame is reused and the key is recorded in FROZEN_USED."""
    file_base = file_base or C.INTERIOR
    try:
        return _slice_from_source(s, sheets, file_base)
    except SourceMissing as e:
        old = _frozen_crop(s["key"], frozen)
        if old is None:
            raise SystemExit(str(e)) from None
        FROZEN_USED.append(s["key"])
        return old


# ----------------------------------------------------------------------------
# scan
# ----------------------------------------------------------------------------

def find_components(im: Image.Image) -> list[tuple[int, int, int, int]]:
    """Return bounding boxes (x, y, w, h) of 8-connected opaque regions."""
    w, h = im.size
    alpha = im.getchannel("A").load()
    seen = bytearray(w * h)
    boxes = []
    for sy in range(h):
        for sx in range(w):
            if seen[sy * w + sx] or alpha[sx, sy] == 0:
                continue
            minx = maxx = sx
            miny = maxy = sy
            q = deque([(sx, sy)])
            seen[sy * w + sx] = 1
            while q:
                x, y = q.popleft()
                minx, maxx = min(minx, x), max(maxx, x)
                miny, maxy = min(miny, y), max(maxy, y)
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < w and 0 <= ny < h and not seen[ny * w + nx] and alpha[nx, ny] != 0:
                            seen[ny * w + nx] = 1
                            q.append((nx, ny))
            boxes.append((minx, miny, maxx - minx + 1, maxy - miny + 1))
    return boxes


def snap(box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    x, y, w, h = box
    x0, y0 = x // C.CELL * C.CELL, y // C.CELL * C.CELL
    x1 = -(-(x + w) // C.CELL) * C.CELL
    y1 = -(-(y + h) // C.CELL) * C.CELL
    return x0, y0, x1 - x0, y1 - y0


def overlaps(a, b) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def merge_overlapping(boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    boxes = list(boxes)
    changed = True
    while changed:
        changed = False
        out: list[tuple[int, int, int, int]] = []
        for b in boxes:
            for i, o in enumerate(out):
                if overlaps(b, o):
                    x0, y0 = min(b[0], o[0]), min(b[1], o[1])
                    x1 = max(b[0] + b[2], o[0] + o[2])
                    y1 = max(b[1] + b[3], o[1] + o[3])
                    out[i] = (x0, y0, x1 - x0, y1 - y0)
                    changed = True
                    break
            else:
                out.append(b)
        boxes = out
    return boxes


def cmd_scan(args: argparse.Namespace) -> None:
    sheet = args.sheet
    table = C.MAP_SHEETS if args.map else C.SHEETS
    slices_file = C.MAP_SLICES_FILE if args.map else C.SLICES_FILE
    path = table.get(sheet) or C.all_sheets().get(sheet)
    if path is None:
        raise SystemExit(f"unknown {'map ' if args.map else ''}sheet '{sheet}' (choices: {', '.join(table)}, "
                         f"or any path from `discover_sheets()`)")
    if not path.exists():
        raise SystemExit(f"sheet '{sheet}' not on disk: {path}")
    safe_name = sheet.replace("/", "_")
    im = Image.open(path).convert("RGBA")
    print(f"scanning {sheet}: {path.name} {im.size}")

    if args.raw:
        # skip 16px-grid snapping AND the overlap-merge pass: for tightly-packed non-LimeZu sheets,
        # snapping bridges small gaps between sprites, and merging by bounding-RECTANGLE overlap
        # (rather than actual touching pixels) falsely fuses non-adjacent sprites whose rects overlap
        # because of irregular silhouettes/packing. Raw flood-fill components are already disjoint.
        boxes = find_components(im)
        boxes = [b for b in boxes if b[2] * b[3] >= args.min_cells * C.CELL * C.CELL]
    else:
        boxes = merge_overlapping(snap(b) for b in find_components(im))
        boxes = [b for b in boxes if (b[2] // C.CELL) * (b[3] // C.CELL) >= args.min_cells]
    boxes.sort(key=lambda b: (b[1], b[0]))

    existing = load_slices(slices_file)
    by_rect = {(s["sheet"], *slice_rect(s)): s for s in existing if "sheet" in s}
    kept = [s for s in existing if s.get("sheet") != sheet]
    named_on_sheet = [s for s in existing if s.get("sheet") == sheet and not s["key"].startswith("auto_")]
    result = list(kept) + named_on_sheet
    named_rects = [slice_rect(s) for s in named_on_sheet]

    n_new = 0
    counter = 1
    for b in boxes:
        key = (sheet, *b)
        if key in by_rect:
            if by_rect[key] not in result:
                result.append(by_rect[key])
            continue
        # skip auto boxes that overlap a manually named slice (user already split/renamed it)
        if any(overlaps(b, r) for r in named_rects):
            continue
        while any(s["key"] == f"auto_{safe_name}_{counter:03d}" for s in result):
            counter += 1
        result.append({"key": f"auto_{safe_name}_{counter:03d}", "sheet": sheet,
                       "x": b[0], "y": b[1], "w": b[2], "h": b[3]})
        counter += 1
        n_new += 1

    save_slices(result, slices_file)
    print(f"{len(boxes)} regions found, {n_new} new auto entries → {slices_file.name}")
    render_contact_sheet(sheet, [s for s in result if s.get("sheet") == sheet], path=path, safe_name=safe_name)


def render_contact_sheet(sheet: str, slices: list[dict], scale: int = 3, path: Path | None = None,
                         safe_name: str | None = None) -> None:
    safe_name = safe_name or sheet
    im = Image.open(path or C.SHEETS[sheet]).convert("RGBA")
    big = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    bg = Image.new("RGBA", big.size, (255, 255, 255, 255))
    bg.alpha_composite(big)
    d = ImageDraw.Draw(bg)
    for s in slices:
        x, y, w, h = slice_rect(s)
        color = (0, 160, 0, 255) if not s["key"].startswith("auto_") else (220, 0, 0, 255)
        d.rectangle([x * scale, y * scale, (x + w) * scale - 1, (y + h) * scale - 1], outline=color)
        label = s["key"].replace(f"auto_{safe_name}_", "#")
        d.rectangle([x * scale, y * scale, x * scale + 6 * len(label) + 2, y * scale + 10], fill=(255, 255, 255, 220))
        d.text((x * scale + 1, y * scale), label, fill=color)
    out = C.CONTACT_SHEET.with_name(f"contact_{safe_name}.png")
    bg.save(out)
    print(f"contact sheet → {out}")


# ----------------------------------------------------------------------------
# build
# ----------------------------------------------------------------------------

def pack_atlas(slices: list[dict], sheet_paths: dict[str, Path] | None = None, image_name: str = "interiors.png",
               file_base: Path | None = None, frozen: tuple[Image.Image, dict] | None = None) -> tuple[Image.Image, dict]:
    """Simple shelf packing. Returns (atlas image, Phaser JSON-hash atlas).
    Slices whose source is missing fall back to `frozen` (see slice_image); FROZEN_USED lists them afterwards."""
    sheet_paths = C.all_sheets() if sheet_paths is None else sheet_paths
    FROZEN_USED.clear()
    sheets = SheetStore(sheet_paths)
    crops = [(s["key"], slice_image(s, sheets, file_base=file_base, frozen=frozen)) for s in slices]
    crops.sort(key=lambda kc: (-kc[1].height, -kc[1].width, kc[0]))

    max_w = 2048  # keep both sides ≤ 4096: mobile WebGL rejects taller textures (was 512 wide × 7000+ tall → black room)
    pad = 1
    shelves: list[list[int]] = []  # [y, height, cursor_x]
    placed: dict[str, tuple[int, int, int, int]] = {}
    for key, crop in crops:
        w, h = crop.size
        for shelf in shelves:
            if shelf[1] >= h and shelf[2] + w + pad <= max_w:
                placed[key] = (shelf[2], shelf[0], w, h)
                shelf[2] += w + pad
                break
        else:
            y = shelves[-1][0] + shelves[-1][1] + pad if shelves else 0
            shelves.append([y, h, w + pad])
            placed[key] = (0, y, w, h)
    total_h = shelves[-1][0] + shelves[-1][1] if shelves else 1
    atlas = Image.new("RGBA", (max_w, total_h), (0, 0, 0, 0))
    frames = {}
    for key, crop in crops:
        x, y, w, h = placed[key]
        atlas.paste(crop, (x, y))
        frames[key] = {
            "frame": {"x": x, "y": y, "w": w, "h": h},
            "rotated": False, "trimmed": False,
            "spriteSourceSize": {"x": 0, "y": 0, "w": w, "h": h},
            "sourceSize": {"w": w, "h": h},
        }
    meta = {"image": image_name, "size": {"w": atlas.width, "h": atlas.height}, "scale": "1"}
    return atlas, {"frames": frames, "meta": meta}


def report_frozen(what: str, slices: list[dict]) -> None:
    """Loud warning listing every slice that was copied from the previous atlas, grouped by source."""
    if not FROZEN_USED:
        return
    by_src: dict[str, list[str]] = {}
    spec = {s["key"]: s for s in slices}
    for key in FROZEN_USED:
        s = spec.get(key, {})
        src = s.get("sheet") or (s["parts"][0].get("sheet") if s.get("parts") else None) or f"file:{s.get('file')}"
        by_src.setdefault(str(src), []).append(key)
    print(f"WARNING: {len(FROZEN_USED)} {what} slices copied from the previous atlas because their source is missing:")
    for src, keys in sorted(by_src.items()):
        shown = ", ".join(keys[:8]) + (f", … (+{len(keys) - 8})" if len(keys) > 8 else "")
        print(f"  {src} ({len(keys)}): {shown}")
    print("  (editing those slices' rects has no effect until the source is back on disk)")


_THEME_SORTER = re.compile(r"Theme_Sorter/\d+_(.+?)(?:_16x16)?\.png$")


def set_of(sl: dict) -> str | None:
    """The furniture set a slice belongs to: a short slug of its source (same source → same set).

    SHEETS keys map through C.SET_ALIASES; discovered Modern Interiors theme files become `mi_<theme>`; other
    discovered PNGs use their file stem; `file` slices use their top folder; `parts` follow the first part.
    None for slices with no source. Set slugs never contain "sheet" (the catalog output is checked for it).
    """
    src = sl.get("sheet") or sl.get("file")
    if src is None and sl.get("parts"):
        return set_of(sl["parts"][0])
    if not src:
        return None
    if "sheet" in sl and src in C.SET_ALIASES:
        slug = C.SET_ALIASES[src]
    elif "sheet" in sl and "/" not in src:
        slug = src
    elif (m := _THEME_SORTER.search(src)):
        slug = "mi_" + m.group(1)
    elif "sheet" in sl:
        slug = Path(src).stem
    else:
        slug = src.split("/")[0]
    slug = re.sub(r"[^a-z0-9]+", "_", slug.lower()).strip("_")
    if "sheet" in slug:
        raise SystemExit(f"slice {sl.get('key')}: set slug '{slug}' must not contain 'sheet'")
    return slug or None


def atlas_keys(atlas_json: dict, slices: list[dict] | None = None, sets: bool = False) -> dict:
    """Manifest entry per frame: size in px/cells plus the tile metadata (step/walk) set on the slice.

    With sets=True (the interiors atlas) each key also carries its furniture `set` (see set_of()).
    """
    keys = {k: {"w": f["frame"]["w"], "h": f["frame"]["h"],
                "cw": f["frame"]["w"] // C.CELL, "ch": f["frame"]["h"] // C.CELL}
            for k, f in atlas_json["frames"].items()}
    for sl in slices or []:
        k = sl["key"]
        if k not in keys:
            continue
        if sets and (s := set_of(sl)):
            keys[k]["set"] = s
        step = sl.get("step")
        if step is not None:
            if step not in TILE_STEPS:
                raise SystemExit(f"slice {k}: step must be one of {', '.join(TILE_STEPS)} (got {step!r})")
            keys[k]["step"] = step
        if sl.get("walk") is False:
            keys[k]["walk"] = False
    return keys


def _strip(v: dict, anim: str) -> Image.Image:
    """One 24-frame strip (384x32) for a variant: cropped from a generator sheet or an explicit file."""
    expected = C.FRAME_W * C.FRAMES_PER_DIR * len(C.DIRS)
    if v.get("sheet") is None and anim not in v:
        return Image.new("RGBA", (expected, C.FRAME_H), (0, 0, 0, 0))  # "none" variant
    if "sheet" in v:
        row = C.GEN_ROWS[anim]
        im = Image.open(v["sheet"]).convert("RGBA")
        st = im.crop((0, row * C.FRAME_H, expected, (row + 1) * C.FRAME_H))
    else:
        st = Image.open(v[anim]).convert("RGBA")
    if st.size != (expected, C.FRAME_H):
        raise SystemExit(f"{v.get('name')} {anim}: expected {expected}x{C.FRAME_H}, got {st.size}")
    if v.get("recolor"):
        st = recolor(st, v["recolor"])
    return st


def recolor(im: Image.Image, mapping: dict) -> Image.Image:
    """Exact palette swap: every pixel whose RGB is a key becomes the mapped RGB (alpha kept)."""
    px = im.load()
    for y in range(im.height):
        for x in range(im.width):
            r, g, b, a = px[x, y]
            new = mapping.get((r, g, b))
            if new is not None and a:
                px[x, y] = (*new, a)
    return im


def build_char_layer(layer: str, variants: list[dict], out_dir: Path) -> dict:
    """Write chars/<layer>/<i>.png (ANIM_STRIPS concatenated) and return the manifest entry."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.png"):
        stale.unlink()
    groups: dict[int, list[int]] = {}
    names = []
    for i, v in enumerate(variants):
        strips = [_strip(v, a) for a in C.ANIM_STRIPS]
        sheet = Image.new("RGBA", (sum(st.width for st in strips), C.FRAME_H), (0, 0, 0, 0))
        x = 0
        for st in strips:
            sheet.paste(st, (x, 0))
            x += st.width
        sheet.save(out_dir / f"{i}.png", optimize=True)
        groups.setdefault(v.get("style", i), []).append(i)
        names.append(v.get("name", str(i)))
    entry: dict = {"count": len(variants), "label": C.LAYER_LABELS.get(layer, layer)}
    # "none" = index of the transparent "nothing" variant (first or last)
    if variants and variants[0].get("name") == "none":
        entry["none"] = 0
    elif variants and variants[-1].get("name") == "none":
        entry["none"] = len(variants) - 1
    if layer in C.EXCLUSIVE_LAYERS:
        entry["exclusive"] = True
    # groups: indices sharing a style (colour variants), in style order; only useful when some group has > 1
    glist = [groups[k] for k in sorted(groups)]
    if any(len(g) > 1 for g in glist):
        entry["groups"] = glist
    entry["names"] = names
    return entry


def build_cat(variant: str | None = None, out_dir: Path | None = None, src: Path | None = None) -> dict | None:
    """gen/cat/<variant>.png: one horizontal strip of the cat's real frames (see config.CATS_DIR for the
    source layout) + the manifest entry {frameW, frameH, variant, file, anims: {"<section>_<dir>": [s, e]}}.
    Empty cells are skipped, so sections may have a different frame count per direction. None when the
    variant PNG is missing (the cat is optional)."""
    variant = variant or C.CAT_VARIANT
    src = src or (C.CATS_DIR / f"{variant}.png")
    if not src.exists():
        print(f"cat: {src} missing — no cat built")
        return None
    out_dir = out_dir or (C.OUT_DIR / "cat")
    cell = C.CAT_CELL
    im = Image.open(src).convert("RGBA")
    frames: list[Image.Image] = []
    anims: dict[str, list[int]] = {}
    for si, section in enumerate(C.CAT_SECTIONS):
        for d, block in C.CAT_DIR_BLOCKS.items():
            start = len(frames)
            for row in (1 + block * 2, 2 + block * 2):
                for col in range(si * 4, si * 4 + 4):
                    fr = im.crop((col * cell, row * cell, (col + 1) * cell, (row + 1) * cell))
                    if fr.getchannel("A").getbbox():
                        frames.append(fr)
            if len(frames) == start:
                raise SystemExit(f"cat {variant}: no frames for {section}_{d} (layout changed?)")
            anims[f"{section}_{d}"] = [start, len(frames) - 1]
    strip = Image.new("RGBA", (cell * len(frames), cell), (0, 0, 0, 0))
    for i, fr in enumerate(frames):
        strip.paste(fr, (i * cell, 0))
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.png"):
        stale.unlink()
    strip.save(out_dir / f"{variant}.png", optimize=True)
    return {"frameW": cell, "frameH": cell, "variant": variant, "file": f"gen/cat/{variant}.png", "anims": anims}


def anim_table() -> dict:
    anims = {}
    base = 0
    for a in C.ANIM_STRIPS:
        for d in C.DIRS:
            anims[f"{a}_{d}"] = [base, base + C.FRAMES_PER_DIR - 1]
            base += C.FRAMES_PER_DIR
    return anims


def check_char_shrink(layers_now: dict[str, list], allow: bool) -> None:
    """Refuse to rebuild a character layer with fewer variants than the shipped manifest: avatar
    indices stored in the DB would silently point at different hair/outfits."""
    manifest = C.OUT_DIR / "manifest.json"
    if not manifest.exists():
        return
    old = json.loads(manifest.read_text(encoding="utf-8")).get("chars", {}).get("layers", {})
    shrunk = {k: (v.get("count", 0), len(layers_now.get(k, []))) for k, v in old.items()
              if len(layers_now.get(k, [])) < v.get("count", 0)}
    if not shrunk:
        return
    msg = ", ".join(f"{k}: {a} → {b}" for k, (a, b) in shrunk.items())
    if allow:
        print(f"WARNING: character layers shrink ({msg}); stored avatar indices may shift")
        return
    raise SystemExit(f"refusing to shrink character layers ({msg}). Is {C.GEN_DIR} on disk? "
                     f"Re-run with --allow-shrink if this is intended.")


def build_map_atlas() -> dict | None:
    """gen/map.png + map.json from map_slices.json. Returns the manifest entry, or None when there are no slices."""
    slices = [s for s in load_slices(C.MAP_SLICES_FILE) if not s["key"].startswith("auto_")]
    if not slices:
        return None
    frozen = load_frozen(C.OUT_DIR / "map.json", C.OUT_DIR / "map.png")
    atlas, atlas_json = pack_atlas(slices, C.all_sheets(), "map.png", file_base=C.ASSETS, frozen=frozen)
    atlas.save(C.OUT_DIR / "map.png", optimize=True)
    (C.OUT_DIR / "map.json").write_text(json.dumps(atlas_json, indent=1), encoding="utf-8")
    print(f"map atlas {atlas.size} with {len(slices)} frames → gen/map.png")
    report_frozen("map", slices)
    return {"atlas": "gen/map.json", "keys": atlas_keys(atlas_json, slices)}


def bg_name(p: Path) -> str:
    """File stem → key usable in map.json (lowercase, [a-z0-9_])."""
    return re.sub(r"[^a-z0-9_]+", "_", p.stem.lower()).strip("_") or "bg"


def copy_map_bgs() -> dict | None:
    """Overworld backdrops → gen/mapbg/<name>.png (plain copies). Names are what map.json's bg_zones refer to."""
    out = C.OUT_DIR / "mapbg"
    if not C.MAP_BG_DIR.exists():
        if out.exists():
            names = sorted(p.stem for p in out.glob("*.png"))
            print("WARNING: assets/graphic/Map/Backgrounds missing; keeping the existing gen/mapbg/")
            return {"names": names} if names else None
        return None
    srcs = sorted(C.MAP_BG_DIR.glob("*.png"))
    if not srcs:
        return None
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("*.png"):
        stale.unlink()
    names: list[str] = []
    for p in srcs:
        n = bg_name(p)
        if n in names:
            raise SystemExit(f"map background name clash: {p.name} → '{n}' already used")
        shutil.copyfile(p, out / f"{n}.png")
        names.append(n)
    print(f"map backgrounds: {len(names)} → gen/mapbg/ ({', '.join(names)})")
    return {"names": names}


def copy_loot_icons(src: Path, key: str, out_name: str, extra: dict[str, object] | None = None) -> dict | None:
    """Loot icons of a data file → gen/<out_name>/<id>.png (DOM overlay images, ore sprites).

    `src[key]` is a list of {id, icon}; `icon` is either an asset path (copied as is) or {file, x, y, w?, h?}
    (a cell cropped out of a sheet, 16x16 by default). `extra` adds named icons the same way ({"pickaxe": icon}).
    """
    if not src.exists():
        return None
    data = json.loads(src.read_text(encoding="utf-8"))
    out = C.OUT_DIR / out_name
    out.mkdir(parents=True, exist_ok=True)
    ids: list[str] = []

    def write(name: str, icon) -> None:
        if not icon:
            return
        if isinstance(icon, str):
            p = C.ASSETS / icon
            if not p.exists():
                print(f"WARNING: {out_name} icon missing for {name}: {icon}")
                return
            shutil.copyfile(p, out / f"{name}.png")
        else:
            p = C.ASSETS / icon["file"]
            if not p.exists():
                print(f"WARNING: {out_name} icon missing for {name}: {icon['file']}")
                return
            x, y = int(icon["x"]), int(icon["y"])
            w, h = int(icon.get("w", C.CELL)), int(icon.get("h", C.CELL))
            with Image.open(p) as im:
                im.convert("RGBA").crop((x, y, x + w, y + h)).save(out / f"{name}.png")
        ids.append(name)

    for entry in data.get(key, []):
        write(entry["id"], entry.get("icon"))
    for name, icon in (extra or {}).items():
        write(name, icon)
    print(f"{out_name} icons: {len(ids)} → gen/{out_name}/")
    return {"icons": ids}


def copy_fish_icons() -> dict | None:
    """data/fishing.json loot icons → gen/fish/<loot id>.png (catch overlay images)."""
    return copy_loot_icons(C.REPO_ROOT / "data" / "fishing.json", "loot", "fish")


def copy_mine_icons() -> dict | None:
    """data/mine.json ore icons + the pickaxe → gen/mine/<id>.png (ore node sprites, 채광 button, overlay)."""
    if not C.MINE_FILE.exists():
        return None
    pick = json.loads(C.MINE_FILE.read_text(encoding="utf-8")).get("pickaxe")
    return copy_loot_icons(C.MINE_FILE, "ores", "mine", {"pickaxe": pick} if pick else None)


def copy_dock() -> dict | None:
    """Dock backdrop layers → gen/dock/<i>.png (plain copies; full-screen layers gain nothing from an atlas)."""
    out = C.OUT_DIR / "dock"
    if not C.DOCK_DIR.exists():
        if out.exists():
            print("WARNING: assets/graphic/Map/Dock missing; keeping the existing gen/dock/")
            layers = sorted(out.glob("*.png"), key=lambda p: int(p.stem))
            if layers:
                with Image.open(layers[0]) as im:
                    return {"layers": len(layers), "w": im.width, "h": im.height}
        else:
            print("WARNING: assets/graphic/Map/Dock missing; no dock backdrop built")
        return None
    srcs = sorted((p for p in C.DOCK_DIR.glob("*.png") if p.stem.isdigit()), key=lambda p: int(p.stem))
    if not srcs:
        print("WARNING: no N.png layers in assets/graphic/Map/Dock")
        return None
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("*.png"):
        stale.unlink()
    size = None
    for i, p in enumerate(srcs):
        with Image.open(p) as im:
            if size is None:
                size = im.size
            elif im.size != size:
                raise SystemExit(f"dock layer {p.name} is {im.size}, expected {size}")
        shutil.copyfile(p, out / f"{i}.png")
    print(f"dock: {len(srcs)} layers {size[0]}x{size[1]} → gen/dock/")
    write_dock_layout(len(srcs), size)
    return {"layers": len(srcs), "w": size[0], "h": size[1]}


def default_dock_layout(n_images: int, size: tuple[int, int]) -> dict:
    """All N.png images back→front, nothing else; bite markers pop up in the lower-middle band (the water)."""
    return {"w": size[0], "h": size[1],
            "layers": [{"kind": "image", "src": i, "x": 0, "y": 0, "visible": True} for i in range(n_images)],
            "water": {"x": 0, "y": int(size[1] * 0.45), "w": size[0], "h": int(size[1] * 0.4)}}


def write_dock_layout(n_images: int, size: tuple[int, int]) -> dict:
    """gen/dock.json = data/dock.json (editor) or the default stack. The client reads only gen/dock.json."""
    layout = default_dock_layout(n_images, size)
    if C.DOCK_FILE.exists():
        layout = json.loads(C.DOCK_FILE.read_text(encoding="utf-8"))
        layout["w"], layout["h"] = size
        kept = [l for l in layout.get("layers", []) if l.get("kind") != "image" or 0 <= int(l.get("src", -1)) < n_images]
        if len(kept) != len(layout.get("layers", [])):
            print("WARNING: data/dock.json referenced image layers that no longer exist; dropped")
        layout["layers"] = kept
    (C.OUT_DIR / "dock.json").write_text(json.dumps(layout, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return layout


def cmd_build(args: argparse.Namespace) -> None:
    slices = [s for s in load_slices() if not s["key"].startswith("auto_")]
    if not slices:
        raise SystemExit("no named slices in slices.json — run `scan`, then rename the auto_ entries you want")
    C.OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not C.GEN_DIR.exists():
        raise SystemExit(f"character generator folder missing: {C.GEN_DIR}")
    check_char_shrink(C.CHAR_LAYERS, getattr(args, "allow_shrink", False))

    frozen = load_frozen(C.OUT_DIR / "interiors.json", C.OUT_DIR / "interiors.png")
    atlas, atlas_json = pack_atlas(slices, frozen=frozen)
    atlas.save(C.OUT_DIR / "interiors.png", optimize=True)
    (C.OUT_DIR / "interiors.json").write_text(json.dumps(atlas_json, indent=1), encoding="utf-8")
    print(f"atlas {atlas.size} with {len(slices)} frames → gen/interiors.png")
    report_frozen("interior", slices)

    layers = {}
    for layer, variants in C.CHAR_LAYERS.items():
        if variants:
            layers[layer] = build_char_layer(layer, variants, C.OUT_DIR / "chars" / layer)
        else:
            layers[layer] = {"count": 0, "label": C.LAYER_LABELS.get(layer, layer)}
        print(f"chars/{layer}: {layers[layer]['count']} variants, {len(layers[layer].get('groups', []))} styles")

    manifest = {
        "chars": {
            "frameW": C.FRAME_W, "frameH": C.FRAME_H,
            "anims": anim_table(),
            "layerOrder": C.LAYER_ORDER,
            "layers": layers,
        },
        "interiors": {"atlas": "gen/interiors.json", "keys": atlas_keys(atlas_json, slices, sets=True)},
    }
    map_entry = build_map_atlas()
    if map_entry:
        manifest["map"] = map_entry
    dock_entry = copy_dock()
    if dock_entry:
        manifest["dock"] = dock_entry
    bg_entry = copy_map_bgs()
    if bg_entry:
        manifest["mapbg"] = bg_entry
    fish_entry = copy_fish_icons()
    if fish_entry:
        manifest["fish"] = fish_entry
    mine_entry = copy_mine_icons()
    if mine_entry:
        manifest["mine"] = mine_entry
    cat_entry = build_cat()
    if cat_entry:
        manifest["cat"] = cat_entry
        print(f"cat/{cat_entry['variant']}: {max(e for _, e in cat_entry['anims'].values()) + 1} frames → gen/cat/")
    (C.OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print("manifest → gen/manifest.json")


# ----------------------------------------------------------------------------
# scaffold items.json
# ----------------------------------------------------------------------------

def cmd_scaffold(_: argparse.Namespace) -> None:
    slices = load_slices()
    data = {"items": []}
    if C.ITEMS_FILE.exists():
        data = json.loads(C.ITEMS_FILE.read_text(encoding="utf-8"))
    have = {it["sprite"] for it in data["items"]}
    added = 0
    for s in slices:
        key = s["key"]
        if key in have or key.startswith("auto_") or key.startswith(TILE_PREFIX):
            continue
        if "file" in s:
            w, h = Image.open(C.INTERIOR / s["file"]).size
        elif "parts" in s:
            w, h = max(p["w"] for p in s["parts"]), sum(p["h"] for p in s["parts"])
        else:
            w, h = s["w"], s["h"]
        cw, ch = max(1, w // C.CELL), max(1, h // C.CELL)
        data["items"].append({
            "id": key, "name": key.replace("_", " "), "price": 50, "sprite": key,
            "w": cw, "h": min(ch, 2) if ch > 1 else 1,  # tall furniture usually occupies less floor than its image
            "layer": "furniture", "is_surface": False, "surface_offset_y": 0,
        })
        added += 1
    C.ITEMS_FILE.parent.mkdir(parents=True, exist_ok=True)
    C.ITEMS_FILE.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{added} placeholder items added → {C.ITEMS_FILE.relative_to(C.REPO_ROOT)} (edit name/price/w/h/layer)")


# ----------------------------------------------------------------------------
# media: BGM + fonts
# ----------------------------------------------------------------------------

FONT_NAMES = {  # source stem (lowercased, spaces removed) -> published stem
    "pf스타더스트3.0": "stardust",
    "pf스타더스트3.0bold": "stardust-bold",
    "pf스타더스트3.0extrabold": "stardust-extrabold",
    "pf스타더스트3.0s": "stardust-s",
    "pf스타더스트3.0sbold": "stardust-s-bold",
    "pf스타더스트3.0sextrabold": "stardust-s-extrabold",
}


def _ascii_slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "x"


SFX_STEP_FOLDER = "walking"  # assets/sfx/walking/<kind>_*.mp3 → step_<kind> (keeps "water" apart from the UI splash)


def sfx_kind(f: Path, root: Path) -> str | None:
    """`<kind>_anything.mp3` → kind. Files under walking/ become `step_<kind>`; legacy/ and unprefixed files are skipped."""
    rel = f.relative_to(root).parts
    if "legacy" in rel[:-1]:
        return None
    m = re.match(r"^([a-z]+)_", f.name)
    if not m:
        return None
    kind = m.group(1)
    return f"step_{kind}" if SFX_STEP_FOLDER in rel[:-1] else kind


def copy_sfx(src: Path | None = None, out: Path | None = None) -> dict[str, int]:
    """assets/sfx/**/<kind>_*.mp3 → media/sfx/<kind>.mp3 (+ <kind>_2.mp3, <kind>_3.mp3 … when a kind has
    several files: the client picks one at random per play). Returns {kind: variant count}, also written to
    media/sfx.json as {"kinds": [...], "variants": {...}}."""
    src = src or C.SFX_DIR
    out = out or (C.MEDIA_DIR / "sfx")
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("*.mp3"):
        stale.unlink()
    groups: dict[str, list[Path]] = {}
    for f in sorted(src.rglob("*.mp3")) if src.exists() else []:
        kind = sfx_kind(f, src)
        if kind is not None:
            groups.setdefault(kind, []).append(f)
    counts: dict[str, int] = {}
    for kind in sorted(groups):
        for i, f in enumerate(groups[kind], start=1):
            shutil.copyfile(f, out / (f"{kind}.mp3" if i == 1 else f"{kind}_{i}.mp3"))
        counts[kind] = len(groups[kind])
    (out.parent / "sfx.json").write_text(json.dumps({"kinds": sorted(counts), "variants": counts}, indent=1) + "\n",
                                         encoding="utf-8")
    return counts


BGM_PERIODS = ("day", "night")
BGM_SKIP_DIRS = {"legacy"}


BGM_NIGHT_PREFIX = "night_"  # a loose `night_*.mp3` in a location folder plays at night only


def _bgm_title(f: Path) -> str:
    stem = f.stem
    return stem[len(BGM_NIGHT_PREFIX):] if stem.lower().startswith(BGM_NIGHT_PREFIX) else stem


def _bgm_tracks(files: list[Path], dst: Path, rel: str, start: int = 1) -> list[dict]:
    """Copy mp3s into dst (NN-slug.mp3, numbered from `start`) and return their manifest rows."""
    tracks: list[dict] = []
    if files:
        dst.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(files, start=start):
        name = f"{i:02d}-{_ascii_slug(_bgm_title(f))[:40]}.mp3"
        shutil.copyfile(f, dst / name)
        tracks.append({"file": f"{rel}/{name}", "title": _bgm_title(f)})
    return tracks


def _period_lists(folder: Path) -> dict[str, list[Path]]:
    """The mp3s that belong to each period of one location folder.

    Loose files: `night_*.mp3` → night, anything else → day. Plus the optional day/ and night/ subfolders.
    """
    loose = sorted(folder.glob("*.mp3")) if folder.exists() else []
    out = {p: sorted((folder / p).glob("*.mp3")) if (folder / p).exists() else [] for p in BGM_PERIODS}
    for f in loose:
        out["night" if f.name.lower().startswith(BGM_NIGHT_PREFIX) else "day"].append(f)
    return out


def build_bgm_manifest(bgm_dir: Path, bgm_out: Path) -> dict[str, dict[str, list[dict]]]:
    """assets/bgm/ → media/bgm/<location>/<period>/NN-slug.mp3 + manifest {location: {day, night}}.

    The top level is the `default` location (rooms, and the fallback for every other place); any other folder
    (e.g. dock/) is a location. In each: loose `night_*.mp3` play at night only, other loose mp3s by day, and
    the optional day/ and night/ subfolders add to those lists. `legacy/` is ignored. An empty list means
    "fall back" (client side: a place without night tracks keeps playing its day list at night).
    """
    if bgm_out.exists():
        shutil.rmtree(bgm_out)
    bgm_out.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict[str, list[dict]]] = {}
    locations: list[tuple[str, Path]] = [("default", bgm_dir)]
    for loc_dir in sorted(bgm_dir.iterdir()) if bgm_dir.exists() else []:
        loc = loc_dir.name.lower()
        if not loc_dir.is_dir() or loc in BGM_PERIODS or loc in BGM_SKIP_DIRS or loc.startswith("."):
            continue
        locations.append((loc, loc_dir))
    for loc, folder in locations:
        lists = _period_lists(folder)
        manifest[loc] = {p: _bgm_tracks(lists[p], bgm_out / loc / p, f"{loc}/{p}") for p in BGM_PERIODS}
    return manifest


def cmd_media(_: argparse.Namespace) -> None:
    manifest = build_bgm_manifest(C.BGM_DIR, C.MEDIA_DIR / "bgm")
    for loc, lists in manifest.items():
        print(f"bgm/{loc}: " + ", ".join(f"{p} {len(t)}" for p, t in lists.items()) + " tracks")
    (C.MEDIA_DIR / "bgm.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    fonts_out = C.MEDIA_DIR / "fonts"
    fonts_out.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in sorted(C.FONTS_DIR.glob("*.ttf")) if C.FONTS_DIR.exists() else []:
        key = f.stem.lower().replace(" ", "")
        stem = FONT_NAMES.get(key, _ascii_slug(f.stem))
        shutil.copyfile(f, fonts_out / f"{stem}.ttf")
        n += 1
    print(f"fonts: {n} files → media/fonts/")

    counts = copy_sfx()
    names = [k if n == 1 else f"{k}×{n}" for k, n in counts.items()]
    print(f"sfx: {len(counts)} sounds → media/sfx/ ({', '.join(names)})")


# ----------------------------------------------------------------------------
# ui: 9-slice frames + theme.css from data/ui_theme.json
# ----------------------------------------------------------------------------

# element selectors whose rounded default look is dropped once a frame is defined for them
FRAME_SELECTORS = {
    "panel": ".panel", "button": "button, button.big", "button_primary": "button.primary", "chip": ".chip",
    "input": "input", "ctx": "#ctx", "toast": "#toast", "note": ".note-paper",
}


def cmd_ui(_: argparse.Namespace) -> None:
    theme = json.loads(C.UI_THEME_FILE.read_text(encoding="utf-8"))
    ui_out = C.MEDIA_DIR / "ui"
    ui_out.mkdir(parents=True, exist_ok=True)
    for stale in ui_out.glob("*.png"):
        stale.unlink()
    scale = int(theme.get("scale", 2))
    font = theme.get("font", {})
    body = font.get("body", "stardust")
    bold = font.get("bold", body)
    # html:root / html-prefixed selectors: theme.css may end up before the bundled style.css, so win on specificity
    lines = ["html:root {"]
    lines.append('  --font-body: "Stardust", -apple-system, "Segoe UI", system-ui, sans-serif;')
    sizes = {"body": int(font.get("size", 15)), "small": 13, "button": None, "big": None, "title": None,
             "preview": 144}
    sizes.update(font.get("sizes", {}))
    lines.append(f"  --font-size: {sizes['body']}px;")
    lines.append(f"  --fs-small: {sizes['small']}px;")
    lines.append(f"  --fs-button: {sizes['button'] or sizes['body']}px;")
    lines.append(f"  --fs-big: {sizes['big'] or sizes['body']}px;")
    lines.append(f"  --fs-title: {sizes['title'] or sizes['body']}px;")
    lines.append(f"  --preview-w: {sizes['preview']}px;")
    # avatar name label (Phaser text): read at runtime by Avatar.ts
    label = theme.get("label", {})
    label_font = label.get("font", "")  # file stem in media/fonts, e.g. "stardust-s"; empty = same as body
    lines.append(f'  --label-font: "{"Label" if label_font else "Stardust"}";')
    lines.append(f"  --label-size: {int(label.get('size', 16))};")
    lines.append(f"  --label-color: {label.get('color', '#ffffff')};")
    lines.append(f"  --label-stroke: {label.get('stroke', '#000000')};")
    lines.append(f"  --label-scale: {label.get('scale', 0.5)};")
    for k, v in theme.get("colors", {}).items():
        lines.append(f"  --{k}: {v};")
    frames = theme.get("frames", {})
    for name, spec in frames.items():
        if "file" in spec:
            src = C.ASSETS_ROOT / spec["file"]
            if not src.exists():
                raise SystemExit(f"frame '{name}': {src} not found")
            im = Image.open(src).convert("RGBA")
        else:
            src = C.ASSETS_ROOT / spec["sheet"]
            if not src.exists():
                raise SystemExit(f"frame '{name}': {src} not found")
            x, y, w, h = spec["x"], spec["y"], spec["w"], spec["h"]
            im = Image.open(src).convert("RGBA").crop((x, y, x + w, y + h))
        sl = int(spec.get("slice", 4))
        if spec.get("fill_inner"):
            # replace everything inside the border with the colour just inside the left edge (removes baked-in labels)
            px = im.load()
            fill = px[sl, im.height // 2]
            for yy in range(sl, im.height - sl):
                for xx in range(sl, im.width - sl):
                    px[xx, yy] = fill
        im.save(ui_out / f"{name}.png", optimize=True)
        css = name.replace("_", "-")
        lines.append(f"  --frame-{css}: url(/media/ui/{name}.png);")
        lines.append(f"  --slice-{css}: {sl};")
        lines.append(f"  --slice-{css}-px: {sl * scale}px;")
        lines.append(f"  --pad-{css}: {int(spec.get('pad', sl)) * scale}px;")
    lines.append("}")
    for name in frames:
        sel = FRAME_SELECTORS.get(name)
        if sel:
            sel = ", ".join("html " + part.strip() for part in sel.split(","))
            lines.append(f"{sel} {{ border-radius: 0; background: none; box-shadow: none; backdrop-filter: none; }}")
    lines.append('@font-face { font-family: "Stardust"; font-weight: 400; src: url(/media/fonts/%s.ttf) format("truetype"); font-display: swap; }' % body)
    lines.append('@font-face { font-family: "Stardust"; font-weight: 700; src: url(/media/fonts/%s.ttf) format("truetype"); font-display: swap; }' % bold)
    if label_font:
        lines.append('@font-face { font-family: "Label"; src: url(/media/fonts/%s.ttf) format("truetype"); font-display: swap; }' % label_font)
    # phones (or any touch screen narrower than the desktop sidebar layout): smaller type, otherwise the bottom
    # 상점/아바타 buttons at `big` px swallow the screen. Defaults cap the desktop sizes; font.sizes_mobile overrides.
    caps = {"body": 15, "small": 13, "button": 15, "big": 20, "title": 18, "preview": 120}
    mobile = {k: min(sizes[k] or sizes["body"], cap) for k, cap in caps.items()}
    mobile.update(font.get("sizes_mobile", {}))
    lines.append("@media (max-width: 899px), (pointer: coarse) {")
    lines.append("  html:root {")
    lines.append(f"    --font-size: {mobile['body']}px;")
    lines.append(f"    --fs-small: {mobile['small']}px;")
    lines.append(f"    --fs-button: {mobile['button']}px;")
    lines.append(f"    --fs-big: {mobile['big']}px;")
    lines.append(f"    --fs-title: {mobile['title']}px;")
    lines.append(f"    --preview-w: {mobile['preview']}px;")
    lines.append("  }")
    lines.append("}")
    (C.MEDIA_DIR / "theme.css").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(frames)} frames → media/ui/, theme.css written")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scan")
    p.add_argument("--sheet", default="interiors", help="key in SHEETS (or MAP_SHEETS with --map)")
    p.add_argument("--min-cells", type=int, default=1)
    p.add_argument("--map", action="store_true", help="scan a MAP_SHEETS sheet into map_slices.json")
    p.add_argument("--raw", action="store_true",
                   help="skip 16px-grid snapping (for tightly-packed sheets where snapping merges neighbours)")
    p.set_defaults(fn=cmd_scan)
    p = sub.add_parser("build")
    p.add_argument("--allow-shrink", action="store_true", help="allow a character layer to lose variants")
    p.set_defaults(fn=cmd_build)
    p = sub.add_parser("shrink", help="downscale 32px sheets to 16px copies the editor can slice")
    p.add_argument("paths", nargs="+", help="PNG files or folders, relative to assets/graphic or absolute")
    p.add_argument("--scale", type=float, default=0.5)
    p.add_argument("--method", choices=("auto", "nearest", "box"), default="auto",
                   help="nearest = pixel-exact for 2x-upscaled art, box = average native hi-res art, auto = detect")
    p.add_argument("--group", choices=("Interior", "Map"), default=None, help="root for sheets outside assets/graphic")
    p.set_defaults(fn=cmd_shrink)
    sub.add_parser("scaffold").set_defaults(fn=cmd_scaffold)
    sub.add_parser("media").set_defaults(fn=cmd_media)
    sub.add_parser("ui").set_defaults(fn=cmd_ui)
    sub.add_parser("editor").set_defaults(fn=lambda _: __import__("editor").main([]))
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
