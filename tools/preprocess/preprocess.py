"""Preprocess raw LimeZu assets into clean sprite sheets + manifest.json.

Usage (from repo root):
    python tools/preprocess/preprocess.py scan [--sheet interiors] [--min-cells 1]
        Finds opaque regions on a sheet, snaps them to the 16px grid, and writes
        candidate slices to slices.json (existing named entries are preserved).
        Also renders contact_sheet.png with every slice outlined and labelled.

    python tools/preprocess/preprocess.py build
        Packs every slice in slices.json into client/public/gen/interiors.png +
        interiors.json (Phaser atlas), builds per-layer character sheets under
        client/public/gen/chars/<layer>/<n>.png, and writes manifest.json.

    python tools/preprocess/preprocess.py scaffold
        Adds a placeholder items.json entry for every atlas key that has none.

    python tools/preprocess/preprocess.py media
        Copies BGM (assets/BGM/{day,night}/*.mp3) and fonts (assets/fonts/*.ttf)
        into client/public/media/ with ASCII names and writes media/bgm.json.

    python tools/preprocess/preprocess.py ui
        Reads data/ui_theme.json, cuts the 9-slice frame PNGs into
        client/public/media/ui/ and writes client/public/media/theme.css.
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


# ----------------------------------------------------------------------------
# slices.json helpers
# ----------------------------------------------------------------------------

def load_slices() -> list[dict]:
    if C.SLICES_FILE.exists():
        return json.loads(C.SLICES_FILE.read_text(encoding="utf-8"))
    return []


def save_slices(slices: list[dict]) -> None:
    slices.sort(key=lambda s: (s.get("sheet", "~file"), s.get("y", 0), s.get("x", 0), s["key"]))
    C.SLICES_FILE.write_text(json.dumps(slices, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def slice_rect(s: dict) -> tuple[int, int, int, int]:
    return s["x"], s["y"], s["w"], s["h"]


def slice_image(s: dict, sheets: dict[str, Image.Image]) -> Image.Image:
    """Crop for a slice: a rect on a named sheet, a standalone PNG (`file`, relative to assets/graphic),
    or `parts` — a list of rects stacked top-to-bottom (for strips split by transparent separators)."""
    if "file" in s:
        path = C.ASSETS / s["file"]
        if not path.exists():
            raise SystemExit(f"file for slice '{s['key']}' not found: {path}")
        return Image.open(path).convert("RGBA")
    if "parts" in s:
        crops = [slice_image({"key": s["key"], **part}, sheets) for part in s["parts"]]
        out = Image.new("RGBA", (max(c.width for c in crops), sum(c.height for c in crops)))
        y = 0
        for c in crops:
            out.paste(c, (0, y))
            y += c.height
        return out
    if s["sheet"] not in sheets:
        raise SystemExit(f"sheet '{s['sheet']}' for slice '{s['key']}' not found")
    x, y, w, h = slice_rect(s)
    return sheets[s["sheet"]].crop((x, y, x + w, y + h))


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
    path = C.SHEETS[sheet]
    im = Image.open(path).convert("RGBA")
    print(f"scanning {sheet}: {path.name} {im.size}")

    boxes = merge_overlapping(snap(b) for b in find_components(im))
    boxes = [b for b in boxes if (b[2] // C.CELL) * (b[3] // C.CELL) >= args.min_cells]
    boxes.sort(key=lambda b: (b[1], b[0]))

    existing = load_slices()
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
        while any(s["key"] == f"auto_{sheet}_{counter:03d}" for s in result):
            counter += 1
        result.append({"key": f"auto_{sheet}_{counter:03d}", "sheet": sheet,
                       "x": b[0], "y": b[1], "w": b[2], "h": b[3]})
        counter += 1
        n_new += 1

    save_slices(result)
    print(f"{len(boxes)} regions found, {n_new} new auto entries → {C.SLICES_FILE.name}")
    render_contact_sheet(sheet, [s for s in result if s.get("sheet") == sheet])


def render_contact_sheet(sheet: str, slices: list[dict], scale: int = 3) -> None:
    im = Image.open(C.SHEETS[sheet]).convert("RGBA")
    big = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    bg = Image.new("RGBA", big.size, (255, 255, 255, 255))
    bg.alpha_composite(big)
    d = ImageDraw.Draw(bg)
    for s in slices:
        x, y, w, h = slice_rect(s)
        color = (0, 160, 0, 255) if not s["key"].startswith("auto_") else (220, 0, 0, 255)
        d.rectangle([x * scale, y * scale, (x + w) * scale - 1, (y + h) * scale - 1], outline=color)
        label = s["key"].replace(f"auto_{sheet}_", "#")
        d.rectangle([x * scale, y * scale, x * scale + 6 * len(label) + 2, y * scale + 10], fill=(255, 255, 255, 220))
        d.text((x * scale + 1, y * scale), label, fill=color)
    out = C.CONTACT_SHEET.with_name(f"contact_{sheet}.png")
    bg.save(out)
    print(f"contact sheet → {out}")


# ----------------------------------------------------------------------------
# build
# ----------------------------------------------------------------------------

def pack_atlas(slices: list[dict]) -> tuple[Image.Image, dict]:
    """Simple shelf packing. Returns (atlas image, Phaser JSON-hash atlas)."""
    sheets = {name: Image.open(p).convert("RGBA") for name, p in C.SHEETS.items() if p.exists()}
    crops = [(s["key"], slice_image(s, sheets)) for s in slices]
    crops.sort(key=lambda kc: (-kc[1].height, -kc[1].width, kc[0]))

    max_w = 512
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
    meta = {"image": "interiors.png", "size": {"w": atlas.width, "h": atlas.height}, "scale": "1"}
    return atlas, {"frames": frames, "meta": meta}


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


def anim_table() -> dict:
    anims = {}
    base = 0
    for a in C.ANIM_STRIPS:
        for d in C.DIRS:
            anims[f"{a}_{d}"] = [base, base + C.FRAMES_PER_DIR - 1]
            base += C.FRAMES_PER_DIR
    return anims


def cmd_build(_: argparse.Namespace) -> None:
    slices = [s for s in load_slices() if not s["key"].startswith("auto_")]
    if not slices:
        raise SystemExit("no named slices in slices.json — run `scan`, then rename the auto_ entries you want")
    C.OUT_DIR.mkdir(parents=True, exist_ok=True)

    atlas, atlas_json = pack_atlas(slices)
    atlas.save(C.OUT_DIR / "interiors.png", optimize=True)
    (C.OUT_DIR / "interiors.json").write_text(json.dumps(atlas_json, indent=1), encoding="utf-8")
    print(f"atlas {atlas.size} with {len(slices)} frames → gen/interiors.png")

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
        "interiors": {
            "atlas": "gen/interiors.json",
            "keys": {k: {"w": f["frame"]["w"], "h": f["frame"]["h"],
                         "cw": f["frame"]["w"] // C.CELL, "ch": f["frame"]["h"] // C.CELL}
                     for k, f in atlas_json["frames"].items()},
        },
    }
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
            w, h = Image.open(C.ASSETS / s["file"]).size
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


def cmd_media(_: argparse.Namespace) -> None:
    bgm_out = C.MEDIA_DIR / "bgm"
    manifest: dict[str, list[dict]] = {}
    for period in ("day", "night"):
        src = C.BGM_DIR / period
        dst = bgm_out / period
        dst.mkdir(parents=True, exist_ok=True)
        for stale in dst.glob("*.mp3"):
            stale.unlink()
        tracks = []
        for i, f in enumerate(sorted(src.glob("*.mp3")) if src.exists() else [], start=1):
            name = f"{i:02d}-{_ascii_slug(f.stem)[:40]}.mp3"
            shutil.copyfile(f, dst / name)
            tracks.append({"file": f"{period}/{name}", "title": f.stem})
        manifest[period] = tracks
        print(f"bgm/{period}: {len(tracks)} tracks")
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


# ----------------------------------------------------------------------------
# ui: 9-slice frames + theme.css from data/ui_theme.json
# ----------------------------------------------------------------------------

# element selectors whose rounded default look is dropped once a frame is defined for them
FRAME_SELECTORS = {
    "panel": ".panel", "button": "button, button.big", "button_primary": "button.primary", "chip": ".chip",
    "input": "input", "ctx": "#ctx", "toast": "#toast",
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
    (C.MEDIA_DIR / "theme.css").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(frames)} frames → media/ui/, theme.css written")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scan")
    p.add_argument("--sheet", default="interiors", choices=list(C.SHEETS))
    p.add_argument("--min-cells", type=int, default=1)
    p.set_defaults(fn=cmd_scan)
    sub.add_parser("build").set_defaults(fn=cmd_build)
    sub.add_parser("scaffold").set_defaults(fn=cmd_scaffold)
    sub.add_parser("media").set_defaults(fn=cmd_media)
    sub.add_parser("ui").set_defaults(fn=cmd_ui)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
