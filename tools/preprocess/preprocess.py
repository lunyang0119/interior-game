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
"""

from __future__ import annotations

import argparse
import json
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
    slices.sort(key=lambda s: (s["sheet"], s["y"], s["x"]))
    C.SLICES_FILE.write_text(json.dumps(slices, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def slice_rect(s: dict) -> tuple[int, int, int, int]:
    return s["x"], s["y"], s["w"], s["h"]


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
    by_rect = {(s["sheet"], *slice_rect(s)): s for s in existing}
    kept = [s for s in existing if s["sheet"] != sheet]
    named_on_sheet = [s for s in existing if s["sheet"] == sheet and not s["key"].startswith("auto_")]
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
    render_contact_sheet(sheet, [s for s in result if s["sheet"] == sheet])


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
    crops = []
    for s in slices:
        if s["sheet"] not in sheets:
            raise SystemExit(f"sheet '{s['sheet']}' for slice '{s['key']}' not found")
        x, y, w, h = slice_rect(s)
        crops.append((s["key"], sheets[s["sheet"]].crop((x, y, x + w, y + h))))
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


def build_char_layer(layer: str, variants: list[dict], out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, v in enumerate(variants):
        strips = [Image.open(v[a]).convert("RGBA") for a in C.ANIM_STRIPS]
        for a, st in zip(C.ANIM_STRIPS, strips):
            expected = C.FRAME_W * C.FRAMES_PER_DIR * len(C.DIRS)
            if st.size != (expected, C.FRAME_H):
                raise SystemExit(f"{layer}[{i}] {a}: expected {expected}x{C.FRAME_H}, got {st.size}")
        sheet = Image.new("RGBA", (sum(s.width for s in strips), C.FRAME_H), (0, 0, 0, 0))
        x = 0
        for st in strips:
            sheet.paste(st, (x, 0))
            x += st.width
        sheet.save(out_dir / f"{i}.png")
    return len(variants)


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
        n = build_char_layer(layer, variants, C.OUT_DIR / "chars" / layer) if variants else 0
        layers[layer] = {"count": n}
        print(f"chars/{layer}: {n} variants")

    manifest = {
        "chars": {
            "frameW": C.FRAME_W, "frameH": C.FRAME_H,
            "anims": anim_table(),
            "layerOrder": C.LAYER_ORDER,
            "layers": layers,
        },
        "interiors": {
            "atlas": "gen/interiors.json",
            "keys": {s["key"]: {"w": s["w"], "h": s["h"], "cw": s["w"] // C.CELL, "ch": s["h"] // C.CELL}
                     for s in slices},
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
        cw, ch = s["w"] // C.CELL, s["h"] // C.CELL
        data["items"].append({
            "id": key, "name": key.replace("_", " "), "price": 50, "sprite": key,
            "w": cw, "h": min(ch, 2) if ch > 1 else 1,  # tall furniture usually occupies less floor than its image
            "layer": "furniture", "is_surface": False, "surface_offset_y": 0,
        })
        added += 1
    C.ITEMS_FILE.parent.mkdir(parents=True, exist_ok=True)
    C.ITEMS_FILE.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{added} placeholder items added → {C.ITEMS_FILE.relative_to(C.REPO_ROOT)} (edit name/price/w/h/layer)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scan")
    p.add_argument("--sheet", default="interiors", choices=list(C.SHEETS))
    p.add_argument("--min-cells", type=int, default=1)
    p.set_defaults(fn=cmd_scan)
    sub.add_parser("build").set_defaults(fn=cmd_build)
    sub.add_parser("scaffold").set_defaults(fn=cmd_scaffold)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
