"""data/train_maps.json: editor-made maps next to the engine's built-ins (app/train/maps.py)."""

import json

from conftest import auth, register

from app import config as app_config
from app.train import maps as M


def rows(*specs):
    return [{"room": r, "device": d, "neighbors": nb, "col": c, "row": rw} for r, d, nb, c, rw in specs]


PAIR = rows(("A1", "curtain", "A2", 1, 1), ("A2", "light", "A1", 2, 1))


def test_validate():
    assert M.validate("ok_map", PAIR) is None
    assert "영문 소문자" in M.validate("Bad-Id", PAIR)
    assert "2개 이상" in M.validate("one", PAIR[:1])
    assert "같은 장치" in M.validate("m", rows(("A1", "curtain", "A2", 1, 1), ("A2", "curtain", "A1", 2, 1)))
    assert "대칭" in M.validate("m", rows(("A1", "curtain", "A2", 1, 1), ("A2", "light", "", 2, 1)))
    assert "연결" in M.validate("m", rows(("A1", "curtain", "", 1, 1), ("A2", "light", "", 2, 1)))
    assert "바로 옆" in M.validate("m", rows(("A1", "curtain", "A3", 1, 1), ("A3", "light", "A1", 3, 1)))
    assert "같은 칸" in M.validate("m", rows(("A1", "curtain", "A2", 1, 1), ("A2", "light", "A1", 1, 1)))
    assert "알 수 없는 장치" in M.validate("m", rows(("A1", "tv", "A2", 1, 1), ("A2", "light", "A1", 2, 1)))
    for mid, rs in M.builtin_rows().items():   # every built-in passes the web rules too
        assert M.validate(mid, rs) is None, mid


def test_file_maps_extend_and_replace(tmp_path, monkeypatch):
    p = tmp_path / "train_maps.json"
    monkeypatch.setattr(app_config, "TRAIN_MAPS_PATH", p)
    assert set(M.all_maps()) == set(M.builtin_rows())
    p.write_text(json.dumps({"maps": {"tiny": PAIR, "car2077_9": PAIR, "broken": PAIR[:1]}}), encoding="utf-8")
    allm = M.all_maps()
    assert "tiny" in allm and "broken" not in allm   # a bad map is skipped, not fatal
    assert len(allm["car2077_9"]) == 2               # same id replaces the built-in
    assert set(M.game_map("tiny").rooms) == {"A1", "A2"} and M.game_map("nope") is None


def test_api_lists_file_maps(client, tmp_path, monkeypatch):
    p = tmp_path / "train_maps.json"
    p.write_text(json.dumps({"maps": {"tiny": PAIR}}), encoding="utf-8")
    monkeypatch.setattr(app_config, "TRAIN_MAPS_PATH", p)
    tok = register(client, "mapper")
    ids = [m["id"] for m in client.get("/api/train/maps", headers=auth(tok)).json()["maps"]]
    assert "tiny" in ids and "car2077_9" in ids
    d = client.get("/api/train/maps/tiny", headers=auth(tok)).json()
    assert {r["id"] for r in d["rooms"]} == {"A1", "A2"}
