"""The inn cat: one pet per KST day counts, affection over the last 3 days, and the inn's comfort bonus."""
import json

from conftest import auth, recv, register

from app.cat import affection, day_str, pet
from app.db import connect, now, transaction

DAY = 86400


def _sql(q, *args):
    conn = connect()
    try:
        with transaction(conn):
            return [dict(r) for r in conn.execute(q, args).fetchall()]
    finally:
        conn.close()


def test_pet_twice_same_day_counts_once(client):
    lun = register(client, "lun")
    kim = register(client, "kim")
    assert client.post("/api/cat/pet").status_code == 401

    r = client.post("/api/cat/pet", headers=auth(lun)).json()
    assert r == {"affection": 1, "first_today": True}
    r = client.post("/api/cat/pet", headers=auth(kim)).json()
    assert r == {"affection": 1, "first_today": False}

    rows = _sql("SELECT day, player_id FROM cat_pets")
    assert rows == [{"day": day_str(now()), "player_id": "lun"}]
    events = [e for e in client.get("/api/activity", headers=auth(lun)).json()["events"] if e["kind"] == "cat"]
    assert len(events) == 1
    assert events[0]["player_id"] == "lun" and events[0]["room_id"] == "inn" and events[0]["amount"] == 0


def test_affection_counts_distinct_days_among_the_last_three(client):
    register(client, "lun")
    register(client, "kim")
    conn = connect()
    try:
        t = now()
        with transaction(conn):
            assert pet(conn, "lun", t - 5 * DAY)[1] is True   # too old to count
            assert pet(conn, "lun", t - 2 * DAY)[1] is True
            assert pet(conn, "kim", t - 1 * DAY)[1] is True
            assert pet(conn, "kim", t - 1 * DAY + 60)[1] is False  # same day again
            assert affection(conn, t) == 2
            aff, first, event = pet(conn, "lun", t)
            assert (aff, first) == (3, True) and event["kind"] == "cat"
            assert affection(conn, t + DAY) == 2      # tomorrow the oldest counted day falls out
            assert affection(conn, t + 3 * DAY) == 0
    finally:
        conn.close()


def test_inn_comfort_gets_the_affection_bonus_and_everyone_hears_the_cat(client):
    lun = register(client, "lun")
    kim = register(client, "kim")
    before = client.get("/api/rooms").json()["rooms"]
    inn = next(r for r in before if r["id"] == "inn")["comfort"]["inn"]
    assert inn["affection"] == 0 and inn["score"] == 0

    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": kim}))
        recv(ws, "hello")
        assert client.post("/api/cat/pet", headers=auth(lun)).json()["first_today"] is True
        m = recv(ws, "cat")
        assert m == {"type": "cat", "player": "lun", "affection": 1, "first_today": True}

    rooms = client.get("/api/rooms").json()["rooms"]
    inn = next(r for r in rooms if r["id"] == "inn")["comfort"]["inn"]
    assert inn["affection"] == 1 and inn["score"] == 3  # affection_bonus = 3 per day (data/guests.json)
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
