"""The activity log: events written next to the ledger, the 5-row cap, income rows, migration backfill."""
import json

from conftest import auth, register
from test_fishing import _finish, _holds, _wait_until_judgeable


def test_events_and_cap(client, env):
    lun = register(client, "lun")
    kim = register(client, "kim")
    # a fresh DB after the first sheet fetch: nothing yet (the first snapshot never counts as income)
    r = client.get("/api/activity", headers=auth(lun)).json()
    assert r["events"] == [] and r["max"] == 5 and r["today"] == {"earned": 0, "spent": 0, "fish": 0}
    assert r["progress"] == {} and r["locked"] == []

    uid = client.post("/api/room/place", json={"item_id": "table", "x": 1, "y": 1}, headers=auth(lun)).json()["uid"]
    client.post("/api/room/place", json={"item_id": "cup", "x": 1, "y": 1}, headers=auth(kim))
    cup = [i for i in client.get("/api/room/inn").json()["items"] if i["item_id"] == "cup"][0]["uid"]
    client.delete(f"/api/room/item/{cup}", headers=auth(kim))  # bought → 'remove'
    junk = [i for i in client.get("/api/room/house_a").json()["items"] if i["item_id"] == "junk"][0]["uid"]
    client.delete(f"/api/room/item/{junk}", headers=auth(lun))  # seeded → 'sell'
    cast = client.post("/api/fish/start", headers=auth(lun)).json()
    _wait_until_judgeable(cast)
    fish = _finish(client, lun, cast, _holds(cast, 3)).json()
    assert fish["ok"]

    r = client.get("/api/activity", headers=auth(lun)).json()
    rows = [(e["kind"], e["player_id"], e["room_id"], e["item_id"], e["amount"]) for e in r["events"]]
    assert rows == [("fish", "lun", None, fish["id"], fish["value"]), ("sell", "lun", "house_a", "junk", 40),
                    ("remove", "kim", "inn", "cup", 10), ("place", "kim", "inn", "cup", -10), ("place", "lun", "inn", "table", -100)]
    assert r["today"] == {"earned": 0, "spent": 110, "fish": 1}

    # one more row pushes the oldest one out: only the newest five are ever served
    client.post("/api/room/place", json={"item_id": "chair", "x": 5, "y": 4}, headers=auth(lun))
    r = client.get("/api/activity", headers=auth(lun)).json()
    assert len(r["events"]) == 5 and r["events"][0]["kind"] == "place" and r["events"][0]["item_id"] == "chair"
    assert ("table" not in [e["item_id"] for e in r["events"]])
    assert r["events"][0]["seq"] > r["events"][1]["seq"]

    # income: the sheet changes, a manual sync notices (kim 300 → 450; lun unchanged; a drop is ignored)
    env["sheet"].write_text(json.dumps({"members": [{"id": "lun", "earned": 480}, {"id": "kim", "earned": 450}]}), encoding="utf-8")
    assert client.post("/api/sync", headers=auth(kim)).status_code == 200
    r = client.get("/api/activity", headers=auth(lun)).json()
    assert (r["events"][0]["kind"], r["events"][0]["player_id"], r["events"][0]["amount"]) == ("earn", "kim", 150)
    assert sum(1 for e in r["events"] if e["kind"] == "earn") == 1
    assert r["today"]["earned"] == 150
    assert client.get("/api/activity").status_code == 401


def test_migration_backfills_events_from_ledger(env):
    """An existing DB gets its log from the ledger: purchases, refunds of bought items, junk sales and catches."""
    import sqlite3
    from app import config, db

    conn = db.connect(config.DB_PATH)
    for f in sorted(db.MIGRATIONS_DIR.glob("*.sql")):
        v = int(f.name.split("_", 1)[0])
        if v > 7:
            break
        conn.executescript("BEGIN;\n" + f.read_text(encoding="utf-8") + f"\nPRAGMA user_version = {v};\nCOMMIT;")
    conn.execute("INSERT INTO players(id, token_hash, created_ts) VALUES ('lun', 'x', 0)")
    conn.execute("INSERT INTO items(uid, item_id, x, y, z, parent_uid, placed_by, ts, room_id) VALUES (1, 'chair', 1, 1, 1, NULL, 'lun', 0, 'inn')")
    conn.executemany("INSERT INTO ledger(ts, player_id, amount, kind, item_uid, item_id) VALUES (?, ?, ?, ?, ?, ?)", [
        (10, "lun", 50, "place", 1, "chair"),       # still in the room → room_id inn
        (11, "lun", 100, "place", 2, "table"),      # bought then...
        (12, "lun", -100, "refund", 2, "table"),    # ...removed (full refund)
        (13, "lun", -40, "refund", 3, "junk"),      # never bought → seeded junk sold
        (14, "lun", -5, "fish", None, "fish:anchovy"),
    ])
    conn.close()

    from fastapi.testclient import TestClient
    from app.main import create_app
    with TestClient(create_app()) as client:
        lun = register(client, "lun")
        r = client.get("/api/activity", headers=auth(lun)).json()
        rows = [(e["ts"], e["kind"], e["room_id"], e["item_id"], e["amount"]) for e in r["events"]]
        assert rows == [(14, "fish", None, "anchovy", 5), (13, "sell", None, "junk", 40), (12, "remove", None, "table", 100),
                        (11, "place", None, "table", -100), (10, "place", "inn", "chair", -50)]
    conn = sqlite3.connect(config.DB_PATH)
    assert conn.execute("PRAGMA user_version").fetchone()[0] >= 8
    assert conn.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0] == 0
    conn.close()
