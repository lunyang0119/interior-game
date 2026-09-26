"""Browser-based editor for slices.json / map_slices.json, data/items.json, data/rooms/*.json and data/map.json.

    python tools/preprocess/editor.py                 # opens http://127.0.0.1:8765/
    python tools/preprocess/editor.py --port 9000 --no-browser
    python tools/preprocess/preprocess.py editor      # same thing

/        editor.html  — sheets (every PNG under assets/graphic/Interior + Map), slices, items (tags, pair),
                        single-object PNG browser, character sheets
/world   world.html   — room editor (size, tiles, seeded items, exits) and map editor (tiles, places)

Local dev tool only: stdlib http.server + Pillow, nothing is needed at runtime.
"""

from __future__ import annotations

import argparse
import importlib
import io
import json
import re
import sys
import threading
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
import config as C  # noqa: E402
import preprocess as P  # noqa: E402

HTML_FILE = Path(__file__).with_name("editor.html")
WORLD_FILE = Path(__file__).with_name("world.html")
ROOM_FILE = C.REPO_ROOT / "data" / "room.json"          # legacy single room the game server still reads (mirror of rooms/inn.json)
ROOMS_DIR = C.REPO_ROOT / "data" / "rooms"
MAP_FILE = C.REPO_ROOT / "data" / "map.json"
LAYERS = ["furniture", "surface_item", "floor", "wall", "wallpaper"]
TAG_RE = re.compile(r"^[a-z0-9_]+$")
ROOM_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
# fields the game server's Room model knows; everything else (name, exits, seed) is for later phases
LEGACY_ROOM_FIELDS = ("cols", "rows", "wall_rows", "spawn", "blocked", "zoom", "tiles")

# character layer → assets/custom/<folder> + required file-name prefix (same rules as config._gen_layer)
CHAR_FOLDERS = {
    "skin": ("Bodies", "Body"),
    "eyes": ("Eyes", "Eyes"),
    "outfit": ("Outfits", "Outfit"),
    "hair": ("Hairstyles", "Hairstyle"),
    "acc": ("Accessories", "Accessory"),
}
CHAR_SHEET_SIZE = (896, 656)
CHAR_NAME_RE = re.compile(r"^[A-Za-z]+_\d+(?:_[A-Za-z0-9]+)*\.png$")


def char_state() -> dict:
    """Layers as built in manifest.json + the custom sheets on disk (what a rebuild would pick up)."""
    manifest = C.OUT_DIR / "manifest.json"
    layers = json.loads(manifest.read_text(encoding="utf-8"))["chars"]["layers"] if manifest.exists() else {}
    custom = {}
    for layer, (folder, prefix) in CHAR_FOLDERS.items():
        d = C.CUSTOM_DIR / folder
        files = []
        if d.exists():
            for p in sorted(d.glob("*.png")):
                try:
                    w, h = Image.open(p).size
                except Exception:
                    w, h = 0, 0
                files.append({"name": p.name, "w": w, "h": h, "ok": (w, h) == CHAR_SHEET_SIZE and p.name.startswith(prefix + "_")})
        custom[layer] = {"folder": folder, "prefix": prefix, "files": files}
    return {"layers": layers, "order": C.LAYER_ORDER, "custom": custom, "customDir": str(C.CUSTOM_DIR),
            "frameW": C.FRAME_W, "frameH": C.FRAME_H, "frames": len(C.ANIM_STRIPS) * len(C.DIRS) * C.FRAMES_PER_DIR}
WALL_LAYERS = ("wall", "wallpaper")
PREVIEW_FLOOR_ROWS = 5
PREVIEW_SCALE = 3

_sheet_cache: dict[str, Image.Image] = {}
_lock = threading.Lock()


def sheet_path(name: str) -> Path | None:
    p = C.all_sheets().get(name)
    return p if p and p.exists() else None


def sheet_image(name: str) -> Image.Image:
    with _lock:
        im = _sheet_cache.get(name)
        if im is None:
            im = Image.open(sheet_path(name)).convert("RGBA")
            _sheet_cache[name] = im
        return im


def sheets_for(spec: dict) -> dict[str, Image.Image]:
    names = {r.get("sheet") for r in spec.get("parts", [spec])}
    return {n: sheet_image(n) for n in names if n and sheet_path(n)}


def sheet_list() -> list[dict]:
    """Every sheet the editor can show: named interior sheets, named map sheets, then discovered ones."""
    out = []
    for n, p in C.all_sheets().items():
        group = "map" if C.sheet_group(n) == "map" else "interior"
        named = n in C.SHEETS or n in C.MAP_SHEETS
        entry = {"name": n, "exists": p.exists(), "group": group, "named": named}
        if p.exists():
            try:
                with Image.open(p) as im:
                    entry.update(w=im.width, h=im.height)
            except Exception:
                entry["exists"] = False
        out.append(entry)
    return out


def singles_themes() -> list[dict]:
    if not C.SINGLES_DIR.exists():
        return []
    return [{"name": d.name, "count": sum(1 for _ in d.glob("*.png"))} for d in sorted(C.SINGLES_DIR.iterdir()) if d.is_dir()]


def singles_files(theme: str) -> list[dict]:
    d = C.SINGLES_DIR / theme
    if "/" in theme or "\\" in theme or not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.png"), key=lambda q: (len(q.stem), q.stem)):
        try:
            with Image.open(p) as im:
                w, h = im.size
        except Exception:
            continue
        out.append({"name": p.name, "w": w, "h": h, "file": p.relative_to(C.INTERIOR).as_posix()})
    return out


_frozen: list = []  # [(image, frames)] cached previous interiors atlas, for slices whose source is gone


def frozen_atlas():
    with _lock:
        if not _frozen:
            _frozen.append(P.load_frozen(C.OUT_DIR / "interiors.json", C.OUT_DIR / "interiors.png"))
        return _frozen[0]


def crop_of(spec: dict) -> Image.Image:
    # the preview key must be the real key so a frozen frame can be found
    spec = {"key": "preview", **spec}
    return P.slice_image(spec, sheets_for(spec), frozen=frozen_atlas())


def png_bytes(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def load_room() -> dict:
    rooms = load_rooms()
    if "inn" in rooms:
        return rooms["inn"]
    return json.loads(ROOM_FILE.read_text(encoding="utf-8")) if ROOM_FILE.exists() else {}


def load_rooms() -> dict[str, dict]:
    """data/rooms/<id>.json. Falls back to the legacy data/room.json as room 'inn' when the folder is empty."""
    rooms: dict[str, dict] = {}
    if ROOMS_DIR.exists():
        for p in sorted(ROOMS_DIR.glob("*.json")):
            try:
                rooms[p.stem] = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
    if not rooms and ROOM_FILE.exists():
        legacy = json.loads(ROOM_FILE.read_text(encoding="utf-8"))
        rooms["inn"] = {"id": "inn", "name": "여관", **legacy, "exits": [], "seed": []}
    return rooms


def validate_room(rid: str, room: dict, all_ids: set[str], item_ids: set[str], tile_keys: set[str]) -> str | None:
    if not ROOM_ID_RE.match(rid):
        return f"방 id는 영문 소문자/숫자/_ 로 시작은 영문: {rid}"
    for f in ("cols", "rows", "wall_rows"):
        v = room.get(f)
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            return f"{rid}: {f}가 정수가 아니에요"
    if room["cols"] < 4 or room["rows"] < 2 or room["wall_rows"] >= room["rows"]:
        return f"{rid}: 크기가 이상해요 (cols≥4, rows≥2, wall_rows<rows)"
    sp = room.get("spawn") or {}
    if not (0 <= int(sp.get("x", -1)) < room["cols"] and room["wall_rows"] <= int(sp.get("y", -1)) < room["rows"]):
        return f"{rid}: spawn이 바닥 안에 있어야 해요"
    tiles = room.get("tiles") or {}
    if len(tiles.get("wall", [])) != room["wall_rows"]:
        return f"{rid}: tiles.wall 길이는 wall_rows({room['wall_rows']})와 같아야 해요"
    for k in ("wall", "wall_left", "wall_right"):
        for t in tiles.get(k, []):
            if t not in tile_keys:
                return f"{rid}: 모르는 타일 '{t}' ({k})"
    if tiles.get("floor") not in tile_keys:
        return f"{rid}: 모르는 바닥 타일 '{tiles.get('floor')}'"
    for e in room.get("exits", []):
        if e.get("to") not in all_ids and e.get("to") != "map":
            return f"{rid}: 출구가 모르는 방 '{e.get('to')}'로 가요"
        for f in ("x", "y", "w", "h"):
            if not isinstance(e.get(f), int) or e[f] < 0:
                return f"{rid}: 출구 {f}가 정수가 아니에요"
    for sd in room.get("seed", []):
        if sd.get("item_id") not in item_ids:
            return f"{rid}: 시드에 모르는 아이템 '{sd.get('item_id')}'"
        if not isinstance(sd.get("x"), int) or not isinstance(sd.get("y"), int):
            return f"{rid}: 시드 좌표가 정수가 아니에요"
    return None


def save_rooms(rooms: dict[str, dict]) -> None:
    ROOMS_DIR.mkdir(parents=True, exist_ok=True)
    for stale in ROOMS_DIR.glob("*.json"):
        if stale.stem not in rooms:
            stale.unlink()
    for rid, room in rooms.items():
        room = {"id": rid, **{k: v for k, v in room.items() if k != "id"}}
        (ROOMS_DIR / f"{rid}.json").write_text(json.dumps(room, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    # the game server (until the multi-room phase) reads data/room.json: keep it equal to the inn
    if "inn" in rooms:
        legacy = {k: rooms["inn"][k] for k in LEGACY_ROOM_FIELDS if k in rooms["inn"]}
        ROOM_FILE.write_text(json.dumps(legacy, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def load_map() -> dict:
    if MAP_FILE.exists():
        return json.loads(MAP_FILE.read_text(encoding="utf-8"))
    return {"cols": 32, "rows": 18, "spawn": {"x": 4, "y": 4}, "layers": {"ground": [], "deco": []}, "blocked": [], "places": []}


def validate_map(m: dict, room_ids: set[str], map_keys: set[str]) -> str | None:
    cols, rows = m.get("cols"), m.get("rows")
    if not isinstance(cols, int) or not isinstance(rows, int) or cols < 4 or rows < 4 or cols > 400 or rows > 400:
        return "맵 크기는 4~400칸"
    for lname, grid in (m.get("layers") or {}).items():
        if len(grid) != rows or any(len(r) != cols for r in grid):
            return f"layers.{lname} 크기가 cols×rows와 달라요"
        for r in grid:
            for k in r:
                if k is not None and k not in map_keys:
                    return f"layers.{lname}: 모르는 타일 '{k}' (맵 슬라이스에 없음 — 빌드했나요?)"
    for pl in m.get("places", []):
        if pl.get("room") not in room_ids and pl.get("room") != "dock":
            return f"장소 '{pl.get('name')}'가 모르는 방 '{pl.get('room')}'로 가요"
        if pl.get("sprite") and pl["sprite"] not in map_keys:
            return f"장소 '{pl.get('name')}': 모르는 스프라이트 '{pl['sprite']}'"
    return None


def atlas_keys(name: str) -> set[str]:
    p = C.OUT_DIR / f"{name}.json"
    if not p.exists():
        return set()
    return set(json.loads(p.read_text(encoding="utf-8")).get("frames", {}))


def load_items() -> dict:
    if C.ITEMS_FILE.exists():
        return json.loads(C.ITEMS_FILE.read_text(encoding="utf-8"))
    return {"items": []}


def save_items(data: dict) -> None:
    C.ITEMS_FILE.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def validate_slices(slices: list, seen: set[str] | None = None) -> str | None:
    seen = set() if seen is None else seen
    sheets = C.all_sheets()
    for s in slices:
        key = s.get("key")
        if not key or not isinstance(key, str):
            return "빈 key가 있어요"
        if key in seen:
            return f"key가 겹쳐요: {key}"
        seen.add(key)
        if "scale" in s and (not isinstance(s["scale"], (int, float)) or not 0 < s["scale"] <= 8):
            return f"{key}: scale은 0보다 크고 8 이하"
        if "file" in s:
            continue
        rects = s["parts"] if "parts" in s else [s]
        if not rects:
            return f"{key}: parts가 비어 있어요"
        for r in rects:
            if r.get("sheet") not in sheets:
                return f"{key}: 모르는 sheet '{r.get('sheet')}'"
            for f in ("x", "y", "w", "h"):
                if not isinstance(r.get(f), int) or isinstance(r.get(f), bool):
                    return f"{key}: {f}가 정수가 아니에요"
            if r["w"] <= 0 or r["h"] <= 0:
                return f"{key}: 크기가 0이에요"
    return None


def blit(dst: Image.Image, src: Image.Image, x: int, y: int) -> None:
    """alpha_composite that tolerates a source hanging off the top/left edge."""
    layer = Image.new("RGBA", dst.size, (0, 0, 0, 0))
    layer.paste(src, (x, y))
    dst.alpha_composite(layer)


def room_preview(spec: dict, x: int, y: int, layer: str, w: int, h: int, span: int) -> Image.Image:
    """The slice composited on a small room exactly as the game draws it (see client/src/room/ItemLayer.ts)."""
    room = load_room()
    cell = C.CELL
    cols = int(room.get("cols", 20))
    wall_rows = int(room.get("wall_rows", 3))
    rows = wall_rows + PREVIEW_FLOOR_ROWS
    tiles = room.get("tiles", {})
    by_key = {s["key"]: s for s in P.load_slices()}
    cache: dict[str, Image.Image] = {}

    def tile(key: str | None) -> Image.Image | None:
        if not key or key not in by_key:
            return None
        if key not in cache:
            cache[key] = crop_of(by_key[key])
        return cache[key]

    out = Image.new("RGBA", (cols * cell, rows * cell), (27, 27, 36, 255))
    wall = tiles.get("wall", [])
    for cy in range(rows):
        for cx in range(cols):
            if cy < wall_rows:
                edge = tiles.get("wall_left") if cx == 0 else tiles.get("wall_right") if cx == cols - 1 else None
                column = edge if edge and cy < len(edge) else wall
                key = column[cy] if cy < len(column) else None
            else:
                key = tiles.get("floor")
            t = tile(key)
            if t:
                out.alpha_composite(t, (cx * cell, cy * cell))

    im = crop_of(spec)
    if layer == "wallpaper":
        width = max(1, span) * cell
        strip = Image.new("RGBA", (width, im.height))
        for ox in range(0, width, im.width):
            strip.paste(im, (ox, 0))
        im = strip
    if layer in WALL_LAYERS:
        px, py = x * cell, y * cell
    else:
        px, py = x * cell, (y + h) * cell - im.height
    blit(out, im, px, py)
    # footprint outline so the occupied cells are obvious
    fw = (span if layer == "wallpaper" else w) * cell
    outline = Image.new("RGBA", out.size, (0, 0, 0, 0))
    ImageDraw.Draw(outline).rectangle((x * cell, y * cell, x * cell + fw - 1, y * cell + h * cell - 1), outline=(255, 80, 80, 220))
    out.alpha_composite(outline)
    return out.resize((out.width * PREVIEW_SCALE, out.height * PREVIEW_SCALE), Image.NEAREST)


def run_build() -> str:
    """Runs cmd_build and returns its stdout, with any error text appended."""
    out = io.StringIO()
    real = sys.stdout
    sys.stdout = out
    try:
        with _lock:
            _sheet_cache.clear()
            _frozen.clear()
        importlib.reload(C)  # re-scan assets/custom so sheets uploaded since startup are included
        C.all_sheets(refresh=True)
        P.cmd_build(argparse.Namespace())
    except SystemExit as e:
        print(f"ERROR: {e}")
    except Exception:
        print(traceback.format_exc())
    finally:
        sys.stdout = real
    return out.getvalue()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # only log writes; GETs are noisy
        if self.command != "GET":
            super().log_message(fmt, *args)

    # ---- helpers
    def send_json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, body: bytes, ctype: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else None

    # ---- routes
    def do_GET(self) -> None:
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == "/":
                self.send_bytes(HTML_FILE.read_bytes(), "text/html; charset=utf-8")
            elif u.path == "/world":
                self.send_bytes(WORLD_FILE.read_bytes(), "text/html; charset=utf-8")
            elif u.path == "/api/state":
                room = load_room()
                self.send_json({
                    "sheets": sheet_list(), "slices": P.load_slices(), "map_slices": P.load_slices(C.MAP_SLICES_FILE),
                    "items": load_items()["items"], "layers": LAYERS, "cell": C.CELL,
                    "room": {k: room.get(k) for k in ("cols", "rows", "wall_rows", "tiles")},
                    "singles": singles_themes(),
                    "atlas": {"interior": (C.OUT_DIR / "interiors.json").exists(), "map": (C.OUT_DIR / "map.json").exists()},
                })
            elif u.path == "/api/world":
                manifest = C.OUT_DIR / "manifest.json"
                chars = json.loads(manifest.read_text(encoding="utf-8"))["chars"] if manifest.exists() else None
                self.send_json({
                    "rooms": load_rooms(), "map": load_map(), "items": load_items()["items"], "cell": C.CELL,
                    "layers": LAYERS, "chars": chars,
                    "map_slices": [s for s in P.load_slices(C.MAP_SLICES_FILE) if not s["key"].startswith("auto_")],
                    "tile_keys": sorted(s["key"] for s in P.load_slices() if s["key"].startswith(P.TILE_PREFIX)),
                    "atlas": {"interior": (C.OUT_DIR / "interiors.json").exists(), "map": (C.OUT_DIR / "map.json").exists()},
                })
            elif u.path == "/api/singles":
                self.send_json({"files": singles_files(unquote(q.get("theme", [""])[0]))})
            elif u.path.startswith("/single/"):
                rel = Path(unquote(u.path[len("/single/"):]))
                p = (C.INTERIOR / rel).resolve()
                if not p.is_relative_to(C.INTERIOR.resolve()) or not p.exists() or p.suffix.lower() != ".png":
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self.send_bytes(p.read_bytes(), "image/png")
            elif u.path.startswith("/gen/"):
                rel = Path(unquote(u.path[len("/gen/"):]))
                p = (C.OUT_DIR / rel).resolve()
                if not p.is_relative_to(C.OUT_DIR.resolve()) or not p.exists():
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self.send_bytes(p.read_bytes(), "image/png" if p.suffix == ".png" else "application/json; charset=utf-8")
            elif u.path.startswith("/sheet/"):
                name = unquote(u.path[len("/sheet/"):])
                p = sheet_path(name)
                if not p:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self.send_bytes(p.read_bytes(), "image/png")
            elif u.path == "/api/chars":
                self.send_json(char_state())
            elif u.path.startswith("/chars/"):
                # built strip: gen/chars/<layer>/<n>.png
                rel = Path(u.path[len("/chars/"):])
                p = (C.OUT_DIR / "chars" / rel).resolve()
                if len(rel.parts) != 2 or not p.is_relative_to((C.OUT_DIR / "chars").resolve()) or not p.exists():
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self.send_bytes(p.read_bytes(), "image/png")
            elif u.path == "/api/preview":
                self.send_bytes(png_bytes(crop_of(json.loads(q["spec"][0]))), "image/png")
            elif u.path == "/api/room-preview":
                g = lambda k, d: int(q.get(k, [d])[0])  # noqa: E731
                im = room_preview(json.loads(q["spec"][0]), g("x", 0), g("y", 0), q.get("layer", ["furniture"])[0],
                                  g("w", 1), g("h", 1), g("span", 1))
                self.send_bytes(png_bytes(im), "image/png")
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except (Exception, SystemExit) as e:  # slice_image raises SystemExit on a bad sheet; keep the editor alive
            self.send_json({"error": f"{type(e).__name__}: {e}"}, 400)

    def do_PUT(self) -> None:
        u = urlparse(self.path)
        try:
            body = self.read_json()
            if u.path == "/api/slices":
                # {"slices": [...], "map_slices": [...]} — a bare list is the old interior-only form
                if isinstance(body, list):
                    body = {"slices": body, "map_slices": P.load_slices(C.MAP_SLICES_FILE)}
                interior, mp = body.get("slices"), body.get("map_slices")
                if not isinstance(interior, list) or not isinstance(mp, list):
                    self.send_json({"error": "slices / map_slices가 list가 아니에요"}, 400)
                    return
                seen: set[str] = set()
                err = validate_slices(interior, seen) or validate_slices(mp, seen)
                if err:
                    self.send_json({"error": err}, 400)
                    return
                P.save_slices(interior)
                P.save_slices(mp, C.MAP_SLICES_FILE)
                self.send_json({"ok": True, "slices": P.load_slices(), "map_slices": P.load_slices(C.MAP_SLICES_FILE)})
            elif u.path == "/api/rooms":
                if not isinstance(body, dict) or not body:
                    self.send_json({"error": "rooms가 비었어요"}, 400)
                    return
                if "inn" not in body:
                    self.send_json({"error": "거점 방 'inn'은 지울 수 없어요"}, 400)
                    return
                item_ids = {it["id"] for it in load_items()["items"]}
                tile_keys = {s["key"] for s in P.load_slices() if s["key"].startswith(P.TILE_PREFIX)}
                for rid, room in body.items():
                    err = validate_room(rid, room, set(body), item_ids, tile_keys)
                    if err:
                        self.send_json({"error": err}, 400)
                        return
                save_rooms(body)
                self.send_json({"ok": True, "rooms": load_rooms()})
            elif u.path == "/api/map":
                err = validate_map(body, set(load_rooms()), atlas_keys("map"))
                if err:
                    self.send_json({"error": err}, 400)
                    return
                MAP_FILE.write_text(json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
                self.send_json({"ok": True})
            elif u.path == "/api/items":
                if not isinstance(body, list):
                    self.send_json({"error": "list가 아니에요"}, 400)
                    return
                ids = [it.get("id") for it in body]
                if not all(ids) or len(set(ids)) != len(ids):
                    self.send_json({"error": "id가 비었거나 겹쳐요"}, 400)
                    return
                bad = [it["id"] for it in body if it.get("is_surface") and it.get("layer") != "furniture"]
                if bad:
                    self.send_json({"error": "is_surface는 가구(furniture)만 켤 수 있어요: " + ", ".join(bad)}, 400)
                    return
                # every sprite must reach the atlas: a named (non auto_) slice in slices.json
                keys = {s["key"] for s in P.load_slices() if not s["key"].startswith("auto_")}
                bad = [it["id"] for it in body if it.get("sprite") not in keys]
                if bad:
                    self.send_json({"error": "아틀라스에 없는 sprite (auto_ 이름이거나 슬라이스 없음): " + ", ".join(bad)}, 400)
                    return
                bad = [it["id"] for it in body if it.get("layer") not in LAYERS]
                if bad:
                    self.send_json({"error": "모르는 layer: " + ", ".join(bad)}, 400)
                    return
                for it in body:
                    tags = it.get("tags")
                    if tags is None or tags == []:
                        it.pop("tags", None)
                    elif not isinstance(tags, list) or not all(isinstance(t, str) and TAG_RE.match(t) for t in tags):
                        self.send_json({"error": f"{it['id']}: tags는 영문 소문자/숫자/_ 목록이어야 해요"}, 400)
                        return
                    else:
                        it["tags"] = sorted(set(tags))
                    if not it.get("pair"):
                        it.pop("pair", None)
                    elif it["pair"] not in ids or it["pair"] == it["id"]:
                        self.send_json({"error": f"{it['id']}: pair '{it['pair']}'가 없거나 자기 자신이에요"}, 400)
                        return
                data = load_items()
                data["items"] = body
                save_items(data)
                self.send_json({"ok": True})
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except (Exception, SystemExit) as e:
            self.send_json({"error": f"{type(e).__name__}: {e}"}, 400)

    def do_POST(self) -> None:
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == "/api/build":
                self.send_json({"ok": True, "log": run_build()})
            elif u.path == "/api/char-upload":
                # raw PNG body; ?layer=hair&name=Hairstyle_30_01.png → assets/custom/Hairstyles/
                layer, name = q.get("layer", [""])[0], q.get("name", [""])[0]
                if layer not in CHAR_FOLDERS:
                    self.send_json({"error": f"모르는 레이어 {layer}"}, 400)
                    return
                folder, prefix = CHAR_FOLDERS[layer]
                if not CHAR_NAME_RE.match(name) or not name.startswith(prefix + "_"):
                    self.send_json({"error": f"파일 이름은 {prefix}_번호[_이름]_색번호.png 형식이어야 해요 (예: {prefix}_30_01.png)"}, 400)
                    return
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n)
                try:
                    im = Image.open(io.BytesIO(raw))
                    im.verify()
                    size = Image.open(io.BytesIO(raw)).size
                except Exception:
                    self.send_json({"error": "PNG 파일이 아니에요"}, 400)
                    return
                fitted = False
                if size != CHAR_SHEET_SIZE:
                    if q.get("fit", ["0"])[0] != "1":
                        # tell the page so it can ask before touching the pixels
                        self.send_json({"error": f"시트 크기는 {CHAR_SHEET_SIZE[0]}×{CHAR_SHEET_SIZE[1]}이어야 해요 (지금 {size[0]}×{size[1]})",
                                        "size": list(size), "expected": list(CHAR_SHEET_SIZE), "can_fit": True}, 409)
                        return
                    # fit: keep the top-left, crop what sticks out right/bottom, pad the rest with transparency
                    src = Image.open(io.BytesIO(raw)).convert("RGBA")
                    canvas = Image.new("RGBA", CHAR_SHEET_SIZE, (0, 0, 0, 0))
                    canvas.paste(src.crop((0, 0, min(src.width, CHAR_SHEET_SIZE[0]), min(src.height, CHAR_SHEET_SIZE[1]))), (0, 0))
                    raw = png_bytes(canvas)
                    fitted = True
                d = C.CUSTOM_DIR / folder
                d.mkdir(parents=True, exist_ok=True)
                (d / name).write_bytes(raw)
                self.send_json({"ok": True, "path": str(d / name), "fitted": fitted, "from": list(size)})
            elif u.path == "/api/char-delete":
                body = self.read_json() or {}
                layer, name = body.get("layer"), body.get("name", "")
                if layer not in CHAR_FOLDERS or "/" in name or "\\" in name or not name.endswith(".png"):
                    self.send_json({"error": "잘못된 요청"}, 400)
                    return
                p = C.CUSTOM_DIR / CHAR_FOLDERS[layer][0] / name
                if p.exists():
                    p.unlink()
                self.send_json({"ok": True})
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as e:
            self.send_json({"error": str(e)}, 400)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"slice editor: {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
