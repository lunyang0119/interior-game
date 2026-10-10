"""The inn cat: every tap counts, 100 taps (from everyone together) = +1 affection, up to 3, forever."""
import json

from conftest import auth, recv, register

from app.cat import MAX_TAPS_PER_CALL, TAPS_PER_LEVEL, affection, pet, taps
from app.db import connect, now, transaction


def _sql(q, *args):
    conn = connect()
    try:
        with transaction(conn):
            return [dict(r) for r in conn.execute(q, args).fetchall()]
    finally:
        conn.close()


def test_taps_add_up_across_players_and_level_every_hundred(client):
    lun = register(client, "lun")
    kim = register(client, "kim")
    assert client.post("/api/cat/pet").status_code == 401

    assert client.post("/api/cat/pet", headers=auth(lun)).json() == {"affection": 0, "taps": 1, "leveled": False}
    assert client.post("/api/cat/pet", json={"taps": 49}, headers=auth(kim)).json() == {"affection": 0, "taps": 50, "leveled": False}
    r = client.post("/api/cat/pet", json={"taps": 50}, headers=auth(lun)).json()
    assert r == {"affection": 1, "taps": 100, "leveled": True}

    rows = _sql("SELECT player_id, n FROM cat_taps ORDER BY seq")
    assert rows == [{"player_id": "lun", "n": 1}, {"player_id": "kim", "n": 49}, {"player_id": "lun", "n": 50}]
    act = client.get("/api/activity", headers=auth(lun)).json()
    events = [e for e in act["events"] if e["kind"] == "cat"]
    assert len(events) == 1  # only the level-up is logged
    assert events[0]["player_id"] == "lun" and events[0]["room_id"] == "inn" and events[0]["amount"] == 0
    assert events[0]["data"] == {"affection": 1, "taps": 100}
    assert act["cat"] == {"affection": 1, "taps": 100}


def test_one_request_claims_at_most_fifty_taps_and_affection_caps_at_three(client):
    lun = register(client, "lun")
    r = client.post("/api/cat/pet", json={"taps": 999}, headers=auth(lun)).json()
    assert r["taps"] == MAX_TAPS_PER_CALL
    assert client.post("/api/cat/pet", json={"taps": 0}, headers=auth(lun)).status_code == 422
    conn = connect()
    try:
        with transaction(conn):
            total = taps(conn)
            while total < 3 * TAPS_PER_LEVEL + 20:
                level, total, leveled, event = pet(conn, "lun", 50)
            assert level == 3 and affection(conn) == 3
            level, total, leveled, event = pet(conn, "lun", 50)
            assert (level, leveled, event) == (3, False, None)  # beyond the cap nothing more happens
            n = conn.execute("SELECT COUNT(*) FROM events WHERE kind = 'cat'").fetchone()[0]
            assert n == 3  # one event per level
    finally:
        conn.close()


def test_inn_comfort_gets_the_affection_bonus_and_everyone_hears_the_cat(client):
    lun = register(client, "lun")
    kim = register(client, "kim")
    before = client.get("/api/rooms").json()["rooms"]
    inn = next(r for r in before if r["id"] == "inn")["comfort"]["inn"]
    assert inn["affection"] == 0 and inn["score"] == 0
    conn = connect()
    try:
        with transaction(conn):
            pet(conn, "kim", MAX_TAPS_PER_CALL, now())
            pet(conn, "kim", TAPS_PER_LEVEL - MAX_TAPS_PER_CALL - 1, now())
    finally:
        conn.close()

    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": kim}))
        recv(ws, "hello")
        assert client.post("/api/cat/pet", headers=auth(lun)).json()["leveled"] is True
        m = recv(ws, "cat")
        assert m == {"type": "cat", "player": "lun", "affection": 1, "taps": TAPS_PER_LEVEL, "leveled": True}

    rooms = client.get("/api/rooms").json()["rooms"]
    inn = next(r for r in rooms if r["id"] == "inn")["comfort"]["inn"]
    assert inn["affection"] == 1 and inn["score"] == 3  # affection_bonus = 3 per level (data/guests.json)
    other = next(r for r in rooms if r["id"] == "house_a")["comfort"]["house_a"]
    assert other["affection"] == 0
    assert client.get("/api/activity", headers=auth(lun)).json()["comfort"]["inn"]["affection"] == 1


def test_catalog_exposes_the_cat_strip_when_built(env):
    from app import catalog as cm

    assert cm.load().public()["cat"] is None
    m = json.loads((env["gen"] / "manifest.json").read_text(encoding="utf-8"))
    m["cat"] = {"frameW": 32, "frameH": 32, "variant": "orange_0", "file": "gen/cat/orange_0.png",
                "anims": {"walk_down": [0, 3]}}
    (env["gen"] / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    pub = cm.load().public()
    assert pub["cat"]["variant"] == "orange_0" and pub["cat"]["anims"]["walk_down"] == [0, 3]
    assert "sheet" not in json.dumps(pub)
