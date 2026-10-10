import json
import os
import sys
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVER_DIR.parent
sys.path.insert(0, str(SERVER_DIR))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated DB + fake sheet + a tiny catalog for every test."""
    data = tmp_path / "data"
    gen = tmp_path / "gen"
    data.mkdir()
    gen.mkdir()

    (data / "fake_sheet.json").write_text(json.dumps({
        "members": [{"id": "lun", "earned": 500}, {"id": "kim", "earned": 300}]
    }), encoding="utf-8")
    (data / "items.json").write_text(json.dumps({"items": [
        {"id": "table", "name": "table", "price": 100, "sprite": "table", "w": 2, "h": 1,
         "layer": "furniture", "is_surface": True, "surface_offset_y": 10},
        {"id": "chair", "name": "chair", "price": 50, "sprite": "chair", "w": 1, "h": 1, "layer": "furniture"},
        {"id": "cup", "name": "cup", "price": 10, "sprite": "cup", "w": 1, "h": 1, "layer": "surface_item"},
        {"id": "scrap", "name": "scrap", "price": 3, "sprite": "scrap", "w": 1, "h": 1, "layer": "surface_item", "tags": ["note"]},
        {"id": "tray", "name": "tray", "price": 10, "sprite": "tray", "w": 2, "h": 1, "layer": "surface_item"},
        {"id": "rug", "name": "rug", "price": 30, "sprite": "rug", "w": 2, "h": 2, "layer": "floor", "tags": ["rug"]},
        {"id": "pattern", "name": "pattern", "price": 5, "sprite": "pattern", "w": 2, "h": 2, "layer": "floor"},
        {"id": "frame", "name": "frame", "price": 20, "sprite": "frame", "w": 1, "h": 1, "layer": "wall"},
        {"id": "banner", "name": "banner", "price": 20, "sprite": "banner", "w": 3, "h": 1, "layer": "wall"},
        {"id": "paper", "name": "paper", "price": 15, "sprite": "paper", "w": 2, "h": 1, "layer": "wallpaper"},
        {"id": "junk", "name": "junk", "price": 40, "sprite": "junk", "w": 1, "h": 1, "layer": "furniture", "tags": ["ruined"], "pair": "chair"},
        {"id": "stairs", "name": "stairs", "price": 0, "sprite": "stairs", "w": 1, "h": 1, "layer": "furniture", "tags": ["fixed", "stairs"]},
        {"id": "memo", "name": "memo", "price": 2, "sprite": "memo", "w": 1, "h": 1, "layer": "furniture", "tags": ["note"]},
        {"id": "bed", "name": "bed", "price": 60, "sprite": "bed", "w": 2, "h": 2, "layer": "furniture", "tags": ["bed"]},
        {"id": "divider", "name": "divider", "price": 20, "sprite": "divider", "w": 2, "h": 1, "layer": "wall", "tags": ["partition"]},
        {"id": "gate", "name": "gate", "price": 25, "sprite": "gate", "w": 2, "h": 1, "layer": "wall", "tags": ["partition", "door"]},
    ]}), encoding="utf-8")
    rooms = data / "rooms"
    rooms.mkdir()
    # the base room has no seed so the older tests keep their version/balance arithmetic
    (rooms / "inn.json").write_text(json.dumps({
        "id": "inn", "name": "여관", "cols": 8, "rows": 6, "wall_rows": 1, "spawn": {"x": 4, "y": 4}, "blocked": [[7, 5]], "zoom": 2,
        "tiles": {"wall": ["tile_wall"], "floor": "tile_floor"},
        "exits": [{"x": 7, "y": 4, "w": 1, "h": 1, "to": "house_a", "spawn": {"x": 1, "y": 3}}],
    }, ensure_ascii=False), encoding="utf-8")
    (rooms / "house_a.json").write_text(json.dumps({
        "id": "house_a", "name": "빈 집", "cols": 6, "rows": 5, "wall_rows": 1, "spawn": {"x": 2, "y": 3}, "blocked": [], "zoom": 2,
        "tiles": {"wall": ["tile_wall"], "floor": "tile_floor"},
        # painted floor: a pond tile at (4,3) — unwalkable, nothing can be placed on it
        "floor": [[None] * 6 for _ in range(3)] + [[None, None, None, None, "tile_water", None], [None] * 6],
        "exits": [{"x": 0, "y": 4, "w": 1, "h": 1, "to": "inn", "spawn": {"x": 6, "y": 4}}],
        "seed": [{"item_id": "junk", "x": 3, "y": 2}, {"item_id": "stairs", "x": 5, "y": 1}, {"item_id": "junk", "x": 9, "y": 9},
                 {"item_id": "junk", "x": 3, "y": 2}, {"item_id": "junk", "x": 1, "y": 0}],
    }, ensure_ascii=False), encoding="utf-8")
    (data / "map.json").write_text(json.dumps({
        "cols": 8, "rows": 6, "spawn": {"x": 1, "y": 1},
        "layers": {"ground": [["g"] * 8 for _ in range(6)], "deco": [[None] * 8 for _ in range(6)]},
        "blocked": [[7, 5]],
        "places": [{"room": "inn", "name": "여관", "sprite": "house", "x": 2, "y": 0, "w": 3, "h": 2, "doors": [[3, 2]], "spawn": {"x": 3, "y": 3}},
                   {"room": "dock", "name": "부두", "sprite": "icon_bridge", "x": 6, "y": 3, "w": 1, "h": 1, "doors": [[6, 4]], "spawn": {"x": 6, "y": 5}}],
        "decos": [{"sprite": "tree", "x": 0, "y": 4}],
        "bg_default": "sky", "bg_zones": [{"x": 5, "y": 0, "w": 3, "h": 6, "bg": "sea"}],
    }, ensure_ascii=False), encoding="utf-8")
    # guests: the shipped tuning (tests that care pass their own GuestConfig)
    g = json.loads((Path(__file__).resolve().parents[2] / "data" / "guests.json").read_text(encoding="utf-8"))
    g["special_after"] = None  # the test catalog has no room2; a test gates it explicitly
    (data / "guests.json").write_text(json.dumps(g), encoding="utf-8")
    (data / "fishing.json").write_text(json.dumps({
        "bites": 3, "gap_ms": [100, 100], "window_ms": [200, 200], "hold_ms": [100, 100], "catch_pct": [0, 0, 50, 100],
        "slack_ms": 50, "cooldown_s": 0,
        "loot": [{"id": "anchovy", "name": "멸치", "value": 5, "weight": 1}, {"id": "chest", "name": "보물상자", "value": 200, "weight": 1}],
    }, ensure_ascii=False), encoding="utf-8")
    (gen / "manifest.json").write_text(json.dumps({
        "chars": {"frameW": 16, "frameH": 32, "anims": {}, "layerOrder": ["skin", "eyes", "hair"],
                  "layers": {"skin": {"count": 2}, "eyes": {"count": 3}, "hair": {"count": 2, "none": 1},
                             "preset": {"count": 3, "none": 0, "exclusive": True},
                             "outfit": {"count": 0}, "acc": {"count": 0}}},
        "interiors": {"atlas": "gen/interiors.json",
                      "keys": {**{k: {} for k in ["chair", "rug", "pattern", "frame", "banner", "paper", "junk", "stairs", "memo", "tile_wall", "gate", "scrap"]},
                               "divider": {"ch": 2},  # the divider's picture is 2 rows tall on a 1-row footprint
                               "table": {"set": "oak"}, "bed": {"set": "oak"}, "tray": {"set": "oak"}, "cup": {"set": "pine"},
                               "tile_floor": {"step": "wood"}, "tile_water": {"step": "water", "walk": False}}},
        "map": {"atlas": "gen/map.json", "keys": {**{k: {} for k in ["house", "icon_bridge", "icon_exclamation", "tree"]},
                                                  "g": {"step": "grass"}, "w": {"step": "water", "walk": False}}},
        "mapbg": {"names": ["sky", "sea"]},
    }), encoding="utf-8")

    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("GEN_DIR", str(gen))
    monkeypatch.setenv("STATIC_DIR", str(tmp_path / "nostatic"))
    monkeypatch.setenv("SHEET_URL", "")
    monkeypatch.setenv("FAKE_SHEET_PATH", str(data / "fake_sheet.json"))

    # config reads env at import time → reload it and everything that captured its values
    import importlib
    from app import config
    importlib.reload(config)
    for name in ["app.db", "app.auth", "app.sheet", "app.catalog"]:
        if name in sys.modules:
            importlib.reload(sys.modules[name])
    from app import ratelimit
    ratelimit.limiter.reset()
    return {"data": data, "gen": gen, "sheet": data / "fake_sheet.json", "rooms": rooms}


@pytest.fixture()
def catalog(env):
    from app import catalog as cm
    return cm.load()


@pytest.fixture()
def client(env):
    from fastapi.testclient import TestClient
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def register(client, pid: str) -> str:
    r = client.post("/api/register", json={"id": pid})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def recv(ws, kind: str, skip: tuple[str, ...] = ("event", "progress")) -> dict:
    """Next frame of the given type; log/progress frames (sent on every change) are skipped unless asked for."""
    while True:
        m = ws.receive_json()
        if m["type"] == kind:
            return m
        assert m["type"] in skip, f"expected {kind}, got {m}"
