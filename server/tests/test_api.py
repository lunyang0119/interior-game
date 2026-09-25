import json

from conftest import auth, register


def test_register_flow(client):
    r = client.post("/api/register", json={"id": "nobody"})
    assert r.status_code == 403 and r.json()["error"] == "not_in_sheet"

    token = register(client, "lun")
    assert len(token) > 30
    assert client.post("/api/register", json={"id": "lun"}).status_code == 409

    r = client.get("/api/me", headers=auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "lun"
    assert body["balance"] == 800  # 500 + 300 shared pool
    assert body["avatar"]["skin"] == 0
    assert {c["id"] for c in body["contributions"]} == {"lun", "kim"}

    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers=auth("bad")).status_code == 401


def test_register_rate_limit(client):
    for _ in range(5):
        client.post("/api/register", json={"id": "nobody"})
    assert client.post("/api/register", json={"id": "nobody"}).status_code == 429


def test_place_stack_remove_refund(client):
    lun = register(client, "lun")
    kim = register(client, "kim")

    r = client.post("/api/room/place", json={"item_id": "cup", "x": 2, "y": 2}, headers=auth(lun))
    assert r.status_code == 400 and r.json()["error"] == "needs_surface"

    r = client.post("/api/room/place", json={"item_id": "table", "x": 2, "y": 2}, headers=auth(lun))
    assert r.status_code == 200
    table_uid = r.json()["uid"]
    assert r.json()["balance"] == 700

    r = client.post("/api/room/place", json={"item_id": "cup", "x": 3, "y": 2}, headers=auth(kim))
    assert r.status_code == 200
    cup_uid = r.json()["uid"]
    assert r.json()["balance"] == 690

    room = client.get("/api/room").json()
    assert room["version"] == 2
    cup = next(i for i in room["items"] if i["uid"] == cup_uid)
    assert cup["parent_uid"] == table_uid and cup["z"] == 2 and cup["placed_by"] == "kim"

    # ETag / 304
    r = client.get("/api/room", headers={"If-None-Match": '"2"'})
    assert r.status_code == 304

    # table with a cup on it cannot be removed or moved
    r = client.delete(f"/api/room/item/{table_uid}", headers=auth(kim))
    assert r.status_code == 400 and r.json()["error"] == "has_children"
    r = client.post("/api/room/move", json={"uid": table_uid, "x": 4, "y": 3}, headers=auth(kim))
    assert r.status_code == 400 and r.json()["error"] == "has_children"

    # anyone can remove; full refund
    r = client.delete(f"/api/room/item/{cup_uid}", headers=auth(lun))
    assert r.status_code == 200 and r.json()["balance"] == 700
    r = client.post("/api/room/move", json={"uid": table_uid, "x": 4, "y": 3}, headers=auth(kim))
    assert r.status_code == 200
    r = client.delete(f"/api/room/item/{table_uid}", headers=auth(kim))
    assert r.status_code == 200 and r.json()["balance"] == 800
    assert client.delete(f"/api/room/item/{table_uid}", headers=auth(kim)).status_code == 404


def test_insufficient_funds(client, env):
    env["sheet"].write_text(json.dumps({"members": [{"id": "lun", "earned": 120}]}), encoding="utf-8")
    lun = register(client, "lun")
    assert client.post("/api/room/place", json={"item_id": "table", "x": 2, "y": 2}, headers=auth(lun)).status_code == 200
    r = client.post("/api/room/place", json={"item_id": "table", "x": 4, "y": 2}, headers=auth(lun))
    assert r.status_code == 400 and r.json()["error"] == "insufficient_funds"


def test_avatar_validation(client):
    lun = register(client, "lun")
    ok = {"skin": 1, "hair": 0, "hair_color": 0, "outfit": 0, "acc": 0}
    assert client.put("/api/avatar", json=ok, headers=auth(lun)).status_code == 200
    assert client.get("/api/me", headers=auth(lun)).json()["avatar"]["skin"] == 1
    bad = dict(ok, skin=2)
    assert client.put("/api/avatar", json=bad, headers=auth(lun)).json()["error"] == "bad_skin"
    bad = dict(ok, hair=1)  # layer has 0 variants
    assert client.put("/api/avatar", json=bad, headers=auth(lun)).json()["error"] == "bad_hair"


def test_rotate_and_logins(client):
    lun = register(client, "lun")
    r = client.post("/api/token/rotate", headers=auth(lun))
    assert r.status_code == 200
    new = r.json()["token"]
    assert client.get("/api/me", headers=auth(lun)).status_code == 401
    assert client.get("/api/me", headers=auth(new)).status_code == 200
    logins = client.get("/api/me/logins", headers=auth(new)).json()["logins"]
    actions = [l["action"] for l in logins]
    assert "register" in actions and "rotate" in actions
    assert all(len(l["ip_hash"]) == 16 for l in logins)


def test_catalog_has_no_secrets(client):
    body = client.get("/api/catalog").json()
    assert {i["id"] for i in body["items"]} >= {"table", "cup"}
    assert body["room"]["cols"] == 8
    assert body["chars"]["layers"]["skin"]["count"] == 2
    assert "sheet" not in json.dumps(body).lower()


def test_ws_presence(client):
    lun = register(client, "lun")
    kim = register(client, "kim")
    with client.websocket_connect("/ws") as a:
        a.send_text(json.dumps({"type": "auth", "token": lun}))
        hello = a.receive_json()
        assert hello["type"] == "hello" and hello["you"] == "lun" and hello["online"] == []
        with client.websocket_connect("/ws") as b:
            b.send_text(json.dumps({"type": "auth", "token": kim}))
            hello_b = b.receive_json()
            assert [o["id"] for o in hello_b["online"]] == ["lun"]
            assert a.receive_json()["type"] == "join"
            b.send_text(json.dumps({"type": "move", "x": 1.5, "y": 2.5, "dir": "left", "moving": True}))
            mv = a.receive_json()
            assert mv == {"type": "move", "id": "kim", "x": 1.5, "y": 2.5, "dir": "left", "moving": True}
            # REST change pushes a room version
            client.post("/api/room/place", json={"item_id": "chair", "x": 1, "y": 1}, headers=auth(lun))
            assert a.receive_json() == {"type": "room", "version": 1}
        assert a.receive_json()["type"] == "leave"


def test_ws_bad_auth(client):
    with client.websocket_connect("/ws") as a:
        a.send_text(json.dumps({"type": "auth", "token": "nope"}))
        try:
            a.receive_text()
            assert False, "expected close"
        except Exception:
            pass
