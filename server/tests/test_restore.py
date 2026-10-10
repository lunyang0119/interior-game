"""Restoration stages: pure rules (restore.py) + the DB/API side (progress.py, locks, ws)."""
import importlib
import json
import sys

import pytest

from conftest import auth, recv, register


def _reload_catalog():
    importlib.reload(sys.modules["app.catalog"])
    from app import catalog as cm
    return cm


def _write_room(env, rid: str, **patch):
    p = env["rooms"] / f"{rid}.json"
    room = json.loads(p.read_text(encoding="utf-8"))
    room.update(patch)
    p.write_text(json.dumps(room, ensure_ascii=False), encoding="utf-8")


def _new_room(env, rid: str, **patch):
    """A fresh, empty room (no seed) that exits to the inn."""
    room = {"id": rid, "name": rid, "cols": 6, "rows": 5, "wall_rows": 1, "spawn": {"x": 2, "y": 3}, "blocked": [], "zoom": 2,
            "tiles": {"wall": ["tile_wall"], "floor": "tile_floor"},
            "exits": [{"x": 0, "y": 4, "w": 1, "h": 1, "to": "inn", "spawn": {"x": 6, "y": 4}}]}
    room.update(patch)
    (env["rooms"] / f"{rid}.json").write_text(json.dumps(room, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------- pure rules

def _row(uid, item_id, placed_by="lun"):
    from app.placement import ItemRow
    return ItemRow(uid=uid, item_id=item_id, x=1, y=1, z=1, parent_uid=None, placed_by=placed_by, ts=0, room_id="house_a")


def _stage(**kw):
    from app.restore import Stage
    return Stage.model_validate({"id": "s", "name": "S", "need": [], "reward": [], **kw})


def test_evaluate_each_need(catalog):
    from app.restore import ANY, evaluate
    st = _stage(need=[{"type": "ruined_zero"}, {"type": "placed", "layer": "furniture", "count": 2},
                      {"type": "placed", "tag": "note"}, {"type": "placed", "item_id": "cup"},
                      {"type": "deliver", "count": 3}, {"type": "deliver", "id": "chest"}, {"type": "pool", "amount": 500}])
    items = [_row(1, "junk", "$seed"), _row(2, "chair", "$seed"), _row(3, "chair"), _row(4, "memo"), _row(5, "cup")]
    p = evaluate(catalog, st, 0, items, {"fish": {ANY: 2, "anchovy": 2}}, 450)
    got = [(n.type, n.have, n.want, n.done) for n in p.needs]
    # the seeded chair does not count; the memo is furniture too (2/2); the junk keeps ruined_zero open
    assert got == [("ruined_zero", 1, 0, False), ("placed", 2, 2, True), ("placed", 1, 1, True), ("placed", 1, 1, True),
                   ("deliver", 2, 3, False), ("deliver", 0, 1, False), ("pool", 450, 500, False)]
    assert not p.done
    p = evaluate(catalog, st, 0, [_row(3, "chair"), _row(4, "memo"), _row(5, "cup")],
                 {"fish": {ANY: 4, "anchovy": 3, "chest": 1}}, 900)
    assert p.done and [n.have for n in p.needs] == [0, 2, 1, 1, 3, 1, 500]
    assert p.public()["needs"][0] == {"type": "ruined_zero", "label": "", "have": 0, "want": 0, "done": True}


def test_need_validation():
    from app.restore import Need
    with pytest.raises(ValueError):
        Need.model_validate({"type": "pool"})
    with pytest.raises(ValueError):
        Need.model_validate({"type": "placed", "layer": "furniture", "tag": "bed"})
    with pytest.raises(ValueError):
        _stage(need=[])


def test_locked_rooms_and_validation(catalog):
    from app.restore import locked_rooms, unlock_map, validate_restore
    rooms = dict(catalog.rooms)
    rooms["inn"] = rooms["inn"].model_copy(update={"restore": [
        _stage(id="a", need=[{"type": "ruined_zero"}], reward=[{"type": "unlock", "room": "map"}]),
        _stage(id="b", need=[{"type": "ruined_zero"}], reward=[{"type": "unlock", "room": "house_a"}, {"type": "unlock", "room": "dock"}]),
    ]})
    validate_restore(rooms)
    assert unlock_map(rooms) == {"map": ("inn", 0), "house_a": ("inn", 1), "dock": ("inn", 1)}
    assert locked_rooms(rooms, {}) == {"map", "house_a", "dock"}
    assert locked_rooms(rooms, {"inn": 1}) == {"house_a", "dock"}
    assert locked_rooms(rooms, {"inn": 2}) == set()

    def bad(restore_by_room, msg):
        rs = dict(catalog.rooms)
        for rid, st in restore_by_room.items():
            rs[rid] = rs[rid].model_copy(update={"restore": st})
        with pytest.raises(ValueError, match=msg):
            validate_restore(rs)

    unlock = lambda target: _stage(need=[{"type": "ruined_zero"}], reward=[{"type": "unlock", "room": target}])  # noqa: E731
    bad({"inn": [unlock("nowhere")]}, "unknown place")
    bad({"house_a": [unlock("inn")]}, "base room")
    bad({"house_a": [unlock("house_a")]}, "own room")
    bad({"inn": [unlock("dock")], "house_a": [unlock("dock")]}, "both")
    # house_a is opened by a stage of house_a's own unlocker... no: house_a ← inn's stage, and inn can't be locked.
    # a real cycle needs two lockable rooms: house_a ← house_b and house_b ← house_a
    rs = dict(catalog.rooms)
    rs["house_b"] = rs["house_a"].model_copy(update={"id": "house_b"})
    rs["house_a"] = rs["house_a"].model_copy(update={"restore": [unlock("house_b")]})
    rs["house_b"] = rs["house_b"].model_copy(update={"restore": [unlock("house_a")]})
    with pytest.raises(ValueError, match="cycle"):
        validate_restore(rs)


def test_catalog_rejects_bad_restore(env):
    _write_room(env, "house_a", restore=[{"id": "x", "name": "x", "need": [{"type": "placed", "item_id": "nope"}]}])
    with pytest.raises(ValueError, match="unknown item"):
        _reload_catalog().load()
    _write_room(env, "house_a", restore=[{"id": "x", "name": "x", "need": [{"type": "ruined_zero"}]},
                                         {"id": "x", "name": "y", "need": [{"type": "ruined_zero"}]}])
    with pytest.raises(ValueError, match="duplicate"):
        _reload_catalog().load()


# ---------------------------------------------------------------- DB + API

@pytest.fixture()
def restore_env(env):
    """house_a: clean it → house_b opens; then a chair + pool 900 → the dock opens. house_b is a new, locked room."""
    _write_room(env, "house_a", restore=[
        {"id": "clean", "name": "청소", "need": [{"type": "ruined_zero"}], "reward": [{"type": "unlock", "room": "house_b"}]},
        {"id": "furnish", "name": "꾸미기", "need": [{"type": "placed", "layer": "furniture", "count": 1}, {"type": "pool", "amount": 900}],
         "reward": [{"type": "unlock", "room": "dock"}]},
    ])
    _new_room(env, "house_b")
    _reload_catalog()
    return env


def test_progress_locks_and_stage_completion(restore_env):
    from fastapi.testclient import TestClient
    from app.main import create_app
    env = restore_env
    with TestClient(create_app()) as client:
        lun = register(client, "lun")
        body = client.get("/api/rooms").json()
        assert body["locked"] == ["dock", "house_b"]
        prog = {r["id"]: r["progress"] for r in body["rooms"]}
        assert prog["inn"] is None
        assert prog["house_a"]["stage"] == 0 and prog["house_a"]["total"] == 2 and prog["house_a"]["done"] is False
        cur = prog["house_a"]["current"]
        assert cur["id"] == "clean" and cur["unlocks"] == ["house_b"] and cur["needs"] == [
            {"type": "ruined_zero", "label": "", "have": 3, "want": 0, "done": False}]

        # locked room: no placing, no moving, but the snapshot can be viewed
        r = client.post("/api/room/place", json={"item_id": "chair", "x": 1, "y": 1, "room_id": "house_b"}, headers=auth(lun))
        assert r.status_code == 403 and r.json()["error"] == "room_locked"
        assert client.get("/api/room/house_b").status_code == 200

        with client.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({"type": "auth", "token": lun}))
            ws.receive_json()
            ws.send_text(json.dumps({"type": "enter", "room": "house_b", "x": 1, "y": 1}))
            assert ws.receive_json() == {"type": "error", "code": "room_locked", "room": "house_b"}
            # selling the junk completes the stage mid-request: everyone gets the log rows and the progress picture
            junk = [i["uid"] for i in client.get("/api/room/house_a").json()["items"] if i["item_id"] == "junk"]
            assert len(junk) == 3
            for uid in junk[:2]:
                client.delete(f"/api/room/item/{uid}", headers=auth(lun))
                recv(ws, "room")
                assert recv(ws, "event")["event"]["kind"] == "sell"
            client.delete(f"/api/room/item/{junk[2]}", headers=auth(lun))
            recv(ws, "room")
            assert recv(ws, "event")["event"]["kind"] == "sell"
            stage = recv(ws, "event")["event"]
            assert stage["kind"] == "stage" and stage["room_id"] == "house_a" and stage["data"]["stage"] == "clean"
            prog = recv(ws, "progress")
            assert prog["locked"] == ["dock"] and prog["rooms"]["house_a"]["stage"] == 1
            assert prog["rooms"]["house_a"]["current"]["id"] == "furnish"
            # now house_b accepts us
            ws.send_text(json.dumps({"type": "enter", "room": "house_b", "x": 1, "y": 1}))
            assert recv(ws, "entered")["room"] == "house_b"

        # stage 2: a chair (pool 800 + 3×40 - 50 = 870 < 900) is not enough on its own...
        assert client.post("/api/room/place", json={"item_id": "chair", "x": 1, "y": 1, "room_id": "house_a"}, headers=auth(lun)).status_code == 200
        body = client.get("/api/rooms").json()
        cur = {r["id"]: r["progress"] for r in body["rooms"]}["house_a"]["current"]
        assert [(n["type"], n["have"], n["want"], n["done"]) for n in cur["needs"]] == [("placed", 1, 1, True), ("pool", 870, 900, False)]
        # ...income from the sheet (lun 500 → 600) finishes it and is logged as 'earn'
        env["sheet"].write_text(json.dumps({"members": [{"id": "lun", "earned": 600}, {"id": "kim", "earned": 300}]}), encoding="utf-8")
        assert client.post("/api/sync", headers=auth(lun)).json()["balance"] == 970
        body = client.get("/api/rooms").json()
        assert body["locked"] == [] and {r["id"]: r["progress"] for r in body["rooms"]}["house_a"]["done"] is True
        kinds = [e["kind"] for e in client.get("/api/activity", headers=auth(lun)).json()["events"]]
        assert kinds[:2] == ["stage", "earn"]


def test_already_met_stages_complete_at_startup(env):
    """A DB from before restoration existed: the inn is clean, so its stages complete on the first start."""
    _write_room(env, "inn", restore=[
        {"id": "a", "name": "a", "need": [{"type": "ruined_zero"}], "reward": [{"type": "unlock", "room": "house_a"}]},
        {"id": "b", "name": "b", "need": [{"type": "pool", "amount": 100}], "reward": [{"type": "unlock", "room": "dock"}]},
        {"id": "c", "name": "c", "need": [{"type": "pool", "amount": 10_000}], "reward": [{"type": "unlock", "room": "map"}]},
    ])
    _reload_catalog()
    from fastapi.testclient import TestClient
    from app.main import create_app
    with TestClient(create_app()) as client:
        lun = register(client, "lun")  # the first sheet fetch (pool 800) happens here → stage b
        body = client.get("/api/rooms").json()
        assert body["locked"] == ["map"]
        inn = {r["id"]: r["progress"] for r in body["rooms"]}["inn"]
        assert inn["stage"] == 2 and inn["current"]["id"] == "c"
        acts = client.get("/api/activity", headers=auth(lun)).json()
        assert [e["data"]["stage"] for e in acts["events"] if e["kind"] == "stage"] == ["b", "a"]
    # a restart does not complete them again
    with TestClient(create_app()) as client:
        lun = register(client, "lun")
        acts = client.get("/api/activity", headers=auth(lun)).json()
        assert sum(1 for e in acts["events"] if e["kind"] == "stage") == 2
