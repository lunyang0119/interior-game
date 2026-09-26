"""Browser-based editor for slices.json + data/items.json.

    python tools/preprocess/editor.py                 # opens http://127.0.0.1:8765/
    python tools/preprocess/editor.py --port 9000 --no-browser
    python tools/preprocess/preprocess.py editor      # same thing

Pick a sheet, drag a rectangle on it (snapped to the 16px grid), give it a key, save. The same page edits
the matching items.json row (name / price / footprint / layer), previews the crop and how it sits in the
room, and can run `build`. Local dev tool only: stdlib http.server + Pillow, nothing is needed at runtime.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import threading
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
import config as C  # noqa: E402
import preprocess as P  # noqa: E402

HTML_FILE = Path(__file__).with_name("editor.html")
ROOM_FILE = C.REPO_ROOT / "data" / "room.json"
LAYERS = ["furniture", "surface_item", "floor", "wall", "wallpaper"]
WALL_LAYERS = ("wall", "wallpaper")
PREVIEW_FLOOR_ROWS = 5
PREVIEW_SCALE = 3

_sheet_cache: dict[str, Image.Image] = {}
_lock = threading.Lock()


def sheet_image(name: str) -> Image.Image:
    with _lock:
        im = _sheet_cache.get(name)
        if im is None:
            im = Image.open(C.SHEETS[name]).convert("RGBA")
            _sheet_cache[name] = im
        return im


def sheets_for(spec: dict) -> dict[str, Image.Image]:
    names = {r.get("sheet") for r in spec.get("parts", [spec])}
    return {n: sheet_image(n) for n in names if n in C.SHEETS and C.SHEETS[n].exists()}


def crop_of(spec: dict) -> Image.Image:
    spec = {"key": "preview", **spec}
    return P.slice_image(spec, sheets_for(spec))


def png_bytes(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def load_room() -> dict:
    return json.loads(ROOM_FILE.read_text(encoding="utf-8")) if ROOM_FILE.exists() else {}


def load_items() -> dict:
    if C.ITEMS_FILE.exists():
        return json.loads(C.ITEMS_FILE.read_text(encoding="utf-8"))
    return {"items": []}


def save_items(data: dict) -> None:
    C.ITEMS_FILE.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def validate_slices(slices: list) -> str | None:
    seen: set[str] = set()
    for s in slices:
        key = s.get("key")
        if not key or not isinstance(key, str):
            return "빈 key가 있어요"
        if key in seen:
            return f"key가 겹쳐요: {key}"
        seen.add(key)
        if "file" in s:
            continue
        rects = s["parts"] if "parts" in s else [s]
        if not rects:
            return f"{key}: parts가 비어 있어요"
        for r in rects:
            if r.get("sheet") not in C.SHEETS:
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
            elif u.path == "/api/state":
                sheets = []
                for n, p in C.SHEETS.items():
                    entry = {"name": n, "exists": p.exists()}
                    if p.exists():
                        im = sheet_image(n)
                        entry.update(w=im.width, h=im.height)
                    sheets.append(entry)
                room = load_room()
                self.send_json({
                    "sheets": sheets, "slices": P.load_slices(), "items": load_items()["items"],
                    "layers": LAYERS, "cell": C.CELL,
                    "room": {k: room.get(k) for k in ("cols", "rows", "wall_rows", "tiles")},
                })
            elif u.path.startswith("/sheet/"):
                name = u.path[len("/sheet/"):]
                if name not in C.SHEETS or not C.SHEETS[name].exists():
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self.send_bytes(C.SHEETS[name].read_bytes(), "image/png")
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
                if not isinstance(body, list):
                    self.send_json({"error": "list가 아니에요"}, 400)
                    return
                err = validate_slices(body)
                if err:
                    self.send_json({"error": err}, 400)
                    return
                P.save_slices(body)
                self.send_json({"ok": True, "slices": P.load_slices()})
            elif u.path == "/api/items":
                if not isinstance(body, list):
                    self.send_json({"error": "list가 아니에요"}, 400)
                    return
                ids = [it.get("id") for it in body]
                if not all(ids) or len(set(ids)) != len(ids):
                    self.send_json({"error": "id가 비었거나 겹쳐요"}, 400)
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
        if urlparse(self.path).path == "/api/build":
            self.send_json({"ok": True, "log": run_build()})
        else:
            self.send_error(HTTPStatus.NOT_FOUND)


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
