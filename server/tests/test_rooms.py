"""Phase 1 (tags / ruined / seed) + Phase 2 (multiple rooms, exits, presence rooms)."""
import json

from conftest import auth, register


def test_seed_once_and_sell(env):
    from fastapi.testclient import TestClient
    from app.main import create_app

    with TestClient(create_app()) as client:
        lun = register(client, "lun")
        r = client.get("/api/room/house_a").json()
        # seeds may hang past the edge (9,9) and overlap each other (3,2 twice); only the one on a wall row is skipped
        assert [(i["item_id"], i["x"], i["y"]) for i in r["items"]] == [("junk", 3, 2), ("stairs", 5, 1), ("junk", 9, 9), ("junk", 3, 2)]
        assert all(i["placed_by"] == "$seed" for i in r["items"])
        assert r["ruined"] == 3 and r["version"] == 1
        assert client.get("/api/room").json() == client.get("/api/room/inn").json()
        assert client.get("/api/room/inn").json()["ruined"] == 0
        assert client.get("/api/room/nope").status_code == 404
        # seeding did not touch the pool
        assert client.get("/api/me", headers=auth(lun)).json()["balance"] == 800
        rooms = {x["id"]: x for x in client.get("/api/rooms").json()["rooms"]}
        assert rooms["house_a"]["ruined"] == 3 and rooms["house_a"]["name"] == "빈 집" and rooms["inn"]["ruined"] == 0
        junk_uid = r["items"][0]["uid"]

    # restart: no duplicate seed, version stable
    with TestClient(create_app()) as client:
        lun = register(client, "lun")
        r = client.get("/api/room/house_a").json()
        assert len(r["items"]) == 4 and r["version"] == 1  # reconcile kept the odd seeds too
        # selling the junk pays the pool
        r = client.delete(f"/api/room/item/{junk_uid}", headers=auth(lun))
        assert r.status_code == 200 and r.json()["balance"] == 840 and r.json()["ruined"] == 2 and r.json()["room"] == "house_a"
        assert client.get("/api/room/house_a").json()["ruined"] == 2
        # ...and the inn version did not move
        assert client.get("/api/room/inn").json()["version"] == 0

    # a restart after selling does not bring it back
    with TestClient(create_app()) as client:
        assert [i["item_id"] for i in client.get("/api/room/house_a").json()["items"]] == ["stairs", "junk", "junk"]


def test_ruined_and_fixed_rules(client):
    lun = register(client, "lun")
    r = client.post("/api/room/place", json={"item_id": "junk", "x": 1, "y": 1}, headers=auth(lun))
    assert r.status_code == 400 and r.json()["error"] == "not_for_sale"
    r = client.post("/api/room/place", json={"item_id": "stairs", "x": 1, "y": 1}, headers=auth(lun))
    assert r.status_code == 400 and r.json()["error"] == "not_for_sale"
    stairs = next(i for i in client.get("/api/room/house_a").json()["items"] if i["item_id"] == "stairs")
    r = client.post("/api/room/move", json={"uid": stairs["uid"], "x": 2, "y": 2}, headers=auth(lun))
    assert r.status_code == 400 and r.json()["error"] == "fixed_item"
    r = client.delete(f"/api/room/item/{stairs['uid']}", headers=auth(lun))
    assert r.status_code == 400 and r.json()["error"] == "fixed_item"
    # ruined items can be moved around before selling (a move follows the normal rules again)
    junk = next(i for i in client.get("/api/room/house_a").json()["items"] if i["item_id"] == "junk")
    r = client.post("/api/room/move", json={"uid": junk["uid"], "x": 9, "y": 9}, headers=auth(lun))
    assert r.status_code == 400 and r.json()["error"] == "out_of_bounds"
    r = client.post("/api/room/move", json={"uid": junk["uid"], "x": 1, "y": 2}, headers=auth(lun))
    assert r.status_code == 200 and r.json()["balance"] == 800


def test_rooms_are_isolated(client):
    lun = register(client, "lun")
    r = client.post("/api/room/place", json={"item_id": "chair", "x": 1, "y": 1, "room_id": "house_a"}, headers=auth(lun))
    assert r.status_code == 200 and r.json()["room"] == "house_a"
    uid = r.json()["uid"]
    # same cell in the inn is free; the chair is only in house_a
    assert client.post("/api/room/place", json={"item_id": "chair", "x": 1, "y": 1}, headers=auth(lun)).status_code == 200
    assert [i["item_id"] for i in client.get("/api/room/inn").json()["items"]] == ["chair"]
    assert uid in [i["uid"] for i in client.get("/api/room/house_a").json()["items"]]
    # move validates against the item's own room (house_a is 6 wide: x=7 is out of bounds there)
    r = client.post("/api/room/move", json={"uid": uid, "x": 7, "y": 1}, headers=auth(lun))
    assert r.status_code == 400 and r.json()["error"] == "out_of_bounds"
    r = client.post("/api/room/place", json={"item_id": "chair", "x": 1, "y": 1, "room_id": "nope"}, headers=auth(lun))
    assert r.status_code == 404 and r.json()["error"] == "unknown_room"
    versions = {x["id"]: x["version"] for x in client.get("/api/rooms").json()["rooms"]}
    assert versions == {"inn": 1, "house_a": 2}  # seed + chair
    # a player cannot place onto a seeded item's cells, even the overlapping ones
    r = client.post("/api/room/place", json={"item_id": "chair", "x": 3, "y": 2, "room_id": "house_a"}, headers=auth(lun))
    assert r.status_code == 400 and r.json()["error"] == "collision"


def test_ws_enter_scopes_presence(client):
    lun = register(client, "lun")
    kim = register(client, "kim")
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        a.send_text(json.dumps({"type": "auth", "token": lun}))
        assert a.receive_json()["room"] == "inn"
        b.send_text(json.dumps({"type": "auth", "token": kim}))
        assert [o["id"] for o in b.receive_json()["online"]] == ["lun"]
        assert a.receive_json()["type"] == "join"
        # kim walks into house_a: lun sees a leave, kim gets the room's snapshot
        b.send_text(json.dumps({"type": "enter", "room": "house_a", "x": 1, "y": 3}))
        assert a.receive_json() == {"type": "leave", "id": "kim"}
        entered = b.receive_json()
        assert entered["type"] == "entered" and entered["room"] == "house_a" and entered["online"] == [] and entered["room_version"] == 1
        # moves no longer reach the inn
        b.send_text(json.dumps({"type": "move", "x": 2, "y": 2, "dir": "up", "moving": False}))
        # a room change anywhere still reaches everyone, tagged with its room
        client.post("/api/room/place", json={"item_id": "chair", "x": 1, "y": 1, "room_id": "house_a"}, headers=auth(lun))
        assert a.receive_json() == {"type": "room", "room": "house_a", "version": 2, "balance": 750}
        assert b.receive_json() == {"type": "room", "room": "house_a", "version": 2, "balance": 750}
        # lun follows: sees kim there
        a.send_text(json.dumps({"type": "enter", "room": "house_a", "x": 1, "y": 3}))
        entered = a.receive_json()
        assert entered["type"] == "entered" and [o["id"] for o in entered["online"]] == ["kim"]
        assert entered["online"][0]["x"] == 2.0
        assert b.receive_json()["type"] == "join"
        # unknown room is ignored, scene rooms are fine
        a.send_text(json.dumps({"type": "enter", "room": "nope"}))
        a.send_text(json.dumps({"type": "enter", "room": "dock"}))
        assert a.receive_json()["room"] == "dock"
        assert b.receive_json() == {"type": "leave", "id": "lun"}
        rooms = {x["id"]: x["online"] for x in client.get("/api/rooms").json()["rooms"]}
        assert rooms == {"inn": 0, "house_a": 1}


def test_migration_006_moves_existing_rows_to_inn(env):
    """A DB from before rooms: items get room_id 'inn' and the old version counter carries over."""
    import sqlite3
    from app import config, db

    conn = db.connect(config.DB_PATH)
    # replay migrations up to 004 only, then plant legacy data
    for f in sorted(db.MIGRATIONS_DIR.glob("*.sql")):
        v = int(f.name.split("_", 1)[0])
        if v > 4:
            break
        conn.executescript("BEGIN;\n" + f.read_text(encoding="utf-8") + f"\nPRAGMA user_version = {v};\nCOMMIT;")
    conn.execute("INSERT INTO players(id, token_hash, created_ts) VALUES ('lun', 'x', 0)")
    conn.execute("INSERT INTO items(item_id, x, y, z, parent_uid, placed_by, ts) VALUES ('chair', 1, 1, 1, NULL, 'lun', 0)")
    conn.execute("UPDATE room_meta SET v = 7 WHERE k = 'version'")
    conn.close()

    from fastapi.testclient import TestClient
    from app.main import create_app
    with TestClient(create_app()) as client:
        r = client.get("/api/room/inn").json()
        assert [i["item_id"] for i in r["items"]] == ["chair"] and r["items"][0]["room_id"] == "inn"
        assert r["version"] == 7
    conn = sqlite3.connect(config.DB_PATH)
    assert conn.execute("SELECT COUNT(*) FROM room_meta WHERE k = 'version'").fetchone()[0] == 0
    assert conn.execute("SELECT id FROM players WHERE id = '$seed'").fetchone() is not None
    conn.close()


def test_catalog_rejects_bad_rooms(env):
    import importlib
    import sys
    from app import catalog as cm
    bad = json.loads((env["rooms"] / "house_a.json").read_text(encoding="utf-8"))
    bad["exits"][0]["to"] = "nowhere"
    (env["rooms"] / "house_a.json").write_text(json.dumps(bad), encoding="utf-8")
    try:
        cm.load()
        assert False, "expected ValueError"
    except ValueError as e:
        assert "nowhere" in str(e)
    bad["exits"][0]["to"] = "inn"
    bad["exits"][0]["spawn"] = {"x": 99, "y": 0}
    (env["rooms"] / "house_a.json").write_text(json.dumps(bad), encoding="utf-8")
    try:
        cm.load()
        assert False, "expected ValueError"
    except ValueError as e:
        assert "spawns outside" in str(e)
    importlib.reload(sys.modules["app.catalog"])
