import json

from conftest import auth, register


def test_register_new_nickname_creates_sheet_row(client, env):
    r = client.post("/api/register", json={"id": "새친구"})
    assert r.status_code == 200 and r.json()["created"] is True and r.json()["earned"] == 0
    members = json.loads(env["sheet"].read_text(encoding="utf-8"))["members"]
    assert any(m["id"] == "새친구" and m["earned"] == 0 for m in members)
    me = client.get("/api/me", headers=auth(r.json()["token"])).json()
    assert me["balance"] == 800 and any(c["id"] == "새친구" for c in me["contributions"])


def test_register_partial_nickname(client, env):
    env["sheet"].write_text(json.dumps({"members": [
        {"id": "게쉬틴안나 보니것", "earned": 500}, {"id": "kim", "earned": 300}, {"id": "kimchi", "earned": 1}]},
        ensure_ascii=False), encoding="utf-8")
    r = client.post("/api/register", json={"id": "게쉬틴"})
    assert r.status_code == 200 and r.json()["created"] is False
    assert r.json()["name"] == "게쉬틴안나 보니것" and r.json()["earned"] == 500
    me = client.get("/api/me", headers=auth(r.json()["token"])).json()
    assert me["balance"] == 801 and any(c["id"] == "게쉬틴" for c in me["contributions"])
    # the row now belongs to "게쉬틴": another id cannot claim it
    r = client.post("/api/register", json={"id": "보니것"})
    assert r.status_code == 409 and r.json()["error"] == "nickname_taken"
    # "kim" is an exact match even though "kimchi" also contains it
    assert client.post("/api/register", json={"id": "kim"}).json()["name"] == "kim"
    r = client.post("/api/register", json={"id": "ch"})
    assert r.status_code == 200 and r.json()["name"] == "kimchi"


def test_register_flow(client):
    token = register(client, "lun")
    assert len(token) > 30
    # same nickname again = login: a new token replaces the old one (details in test_register_existing_id_logs_in)
    r = client.post("/api/register", json={"id": "lun"}).json()
    assert r["existing"] is True
    token = r["token"]

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
    for i in range(5):
        client.post("/api/register", json={"id": f"n{i}"})
    assert client.post("/api/register", json={"id": "n9"}).status_code == 429


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
    ok = {"skin": 1, "eyes": 2, "hair": 1, "outfit": 0, "acc": 0, "preset": 2}
    assert client.put("/api/avatar", json=ok, headers=auth(lun)).status_code == 200
    got = client.get("/api/me", headers=auth(lun)).json()["avatar"]
    assert got["skin"] == 1 and got["eyes"] == 2 and got["hair"] == 1 and got["hair_color"] == 0 and got["preset"] == 2
    assert client.put("/api/avatar", json=dict(ok, preset=3), headers=auth(lun)).json()["error"] == "bad_preset"
    bad = dict(ok, skin=2)
    assert client.put("/api/avatar", json=bad, headers=auth(lun)).json()["error"] == "bad_skin"
    bad = dict(ok, eyes=3)
    assert client.put("/api/avatar", json=bad, headers=auth(lun)).json()["error"] == "bad_eyes"
    bad = dict(ok, outfit=1)  # layer has 0 variants
    assert client.put("/api/avatar", json=bad, headers=auth(lun)).json()["error"] == "bad_outfit"
    bad = dict(ok, hair_color=1)  # legacy column: must stay 0
    assert client.put("/api/avatar", json=bad, headers=auth(lun)).json()["error"] == "bad_hair_color"


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
            # ...with the shared pool balance so every client's HUD follows (800 - chair 50)
            assert a.receive_json() == {"type": "room", "version": 1, "balance": 750}
        assert a.receive_json()["type"] == "leave"


def test_ws_bad_auth(client):
    with client.websocket_connect("/ws") as a:
        a.send_text(json.dumps({"type": "auth", "token": "nope"}))
        try:
            a.receive_text()
            assert False, "expected close"
        except Exception:
            pass


def test_register_existing_id_logs_in(client, env):
    """Nickname = login: an existing id gets a new token, the old one dies, items and avatar stay."""
    lun = register(client, "lun")
    assert client.post("/api/room/place", json={"item_id": "chair", "x": 1, "y": 1}, headers=auth(lun)).status_code == 200
    assert client.put("/api/avatar", json={"skin": 1, "eyes": 2, "hair": 0, "outfit": 0, "acc": 0}, headers=auth(lun)).status_code == 200

    r = client.post("/api/register", json={"id": "lun"})
    assert r.status_code == 200, r.text
    assert r.json()["existing"] is True and r.json()["created"] is False
    lun2 = r.json()["token"]
    assert lun2 != lun
    assert client.get("/api/me", headers=auth(lun)).status_code == 401
    me = client.get("/api/me", headers=auth(lun2)).json()
    assert me["id"] == "lun" and me["avatar"]["skin"] == 1
    assert [i["placed_by"] for i in client.get("/api/room").json()["items"]] == ["lun"]


def test_reconcile_removes_items_invalidated_by_room_change(env):
    """Rows placed under an older room layout are dropped + refunded when the server starts."""
    from fastapi.testclient import TestClient
    from app.main import create_app

    with TestClient(create_app()) as client:
        lun = register(client, "lun")
        r = client.post("/api/room/place", json={"item_id": "chair", "x": 1, "y": 1}, headers=auth(lun))  # first floor row
        assert r.status_code == 200 and r.json()["balance"] == 750
        r = client.post("/api/room/place", json={"item_id": "table", "x": 3, "y": 3}, headers=auth(lun))
        assert r.status_code == 200
        version = r.json()["version"]

    room = json.loads((env["data"] / "room.json").read_text(encoding="utf-8"))
    room["wall_rows"] = 2
    room["tiles"]["wall"] = ["tile_wall", "tile_wall"]
    (env["data"] / "room.json").write_text(json.dumps(room), encoding="utf-8")
    import importlib, sys
    importlib.reload(sys.modules["app.catalog"])

    with TestClient(create_app()) as client:
        lun = register(client, "lun")
        items = client.get("/api/room").json()
        assert [i["item_id"] for i in items["items"]] == ["table"]  # chair now sits on a wall row → gone
        assert items["version"] == version + 1
        assert client.get("/api/me", headers=auth(lun)).json()["balance"] == 700  # chair refunded


def test_wallpaper_span_pricing_and_resize(client):
    lun = register(client, "lun")
    r = client.post("/api/room/place", json={"item_id": "paper", "x": 0, "y": 0, "span": 4}, headers=auth(lun))
    assert r.status_code == 200 and r.json()["balance"] == 800 - 60  # 15 per column
    uid = r.json()["uid"]
    item = next(i for i in client.get("/api/room").json()["items"] if i["uid"] == uid)
    assert item["span"] == 4
    # second wallpaper overlapping the first → collision; right after it is fine
    r = client.post("/api/room/place", json={"item_id": "paper", "x": 3, "y": 0, "span": 1}, headers=auth(lun))
    assert r.status_code == 400 and r.json()["error"] == "collision"
    # move + widen: pays the difference
    r = client.post("/api/room/move", json={"uid": uid, "x": 0, "y": 0, "span": 6}, headers=auth(lun))
    assert r.status_code == 200 and r.json()["balance"] == 800 - 90
    # move + shrink: refunds the difference
    r = client.post("/api/room/move", json={"uid": uid, "x": 2, "y": 0, "span": 2}, headers=auth(lun))
    assert r.status_code == 200 and r.json()["balance"] == 800 - 30
    # plain move keeps the width
    r = client.post("/api/room/move", json={"uid": uid, "x": 1, "y": 0}, headers=auth(lun))
    assert r.status_code == 200 and r.json()["balance"] == 800 - 30
    # span on a non-wallpaper item is rejected
    r = client.post("/api/room/place", json={"item_id": "chair", "x": 2, "y": 2, "span": 2}, headers=auth(lun))
    assert r.status_code == 400 and r.json()["error"] == "bad_span"
    # remove refunds the width-based price
    r = client.delete(f"/api/room/item/{uid}", headers=auth(lun))
    assert r.status_code == 200 and r.json()["balance"] == 800
