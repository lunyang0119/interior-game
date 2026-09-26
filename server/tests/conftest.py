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
        {"id": "tray", "name": "tray", "price": 10, "sprite": "tray", "w": 2, "h": 1, "layer": "surface_item"},
        {"id": "rug", "name": "rug", "price": 30, "sprite": "rug", "w": 2, "h": 2, "layer": "floor"},
        {"id": "frame", "name": "frame", "price": 20, "sprite": "frame", "w": 1, "h": 1, "layer": "wall"},
        {"id": "paper", "name": "paper", "price": 15, "sprite": "paper", "w": 2, "h": 1, "layer": "wallpaper"},
    ]}), encoding="utf-8")
    (data / "room.json").write_text(json.dumps({
        "cols": 8, "rows": 6, "wall_rows": 1, "spawn": {"x": 4, "y": 4}, "blocked": [[7, 5]], "zoom": 2,
        "tiles": {"wall": ["tile_wall"], "floor": "tile_floor"},
    }), encoding="utf-8")
    (gen / "manifest.json").write_text(json.dumps({
        "chars": {"frameW": 16, "frameH": 32, "anims": {}, "layerOrder": ["skin", "eyes", "hair"],
                  "layers": {"skin": {"count": 2}, "eyes": {"count": 3}, "hair": {"count": 2, "none": 1},
                             "preset": {"count": 3, "none": 0, "exclusive": True},
                             "outfit": {"count": 0}, "acc": {"count": 0}}},
        "interiors": {"atlas": "gen/interiors.json",
                      "keys": {k: {} for k in ["table", "chair", "cup", "tray", "rug", "frame", "paper", "tile_wall", "tile_floor"]}},
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
    return {"data": data, "gen": gen, "sheet": data / "fake_sheet.json"}


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
