"""Handing a catch in (POST /api/deliver) instead of keeping the money."""
import importlib
import json
import sys

import pytest

from conftest import auth, recv, register
from test_fishing import _finish, _holds, _wait_until_judgeable


@pytest.fixture()
def deliver_env(env):
    """house_a wants two fish (any kind), then opens the dock."""
    p = env["rooms"] / "house_a.json"
    room = json.loads(p.read_text(encoding="utf-8"))
    room["restore"] = [{"id": "fish", "name": "낚시", "need": [{"type": "deliver", "kind": "fish", "count": 2}],
                        "reward": [{"type": "unlock", "room": "dock"}]}]
    p.write_text(json.dumps(room, ensure_ascii=False), encoding="utf-8")
    importlib.reload(sys.modules["app.catalog"])
    return env


def _catch(client, token):
    cast = client.post("/api/fish/start", headers=auth(token)).json()
    _wait_until_judgeable(cast)
    r = _finish(client, token, cast, _holds(cast, 3))
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    return r.json()


def test_deliver_flow(deliver_env):
    from fastapi.testclient import TestClient
    from app.main import create_app
    with TestClient(create_app()) as client:
        lun = register(client, "lun")
        kim = register(client, "kim")
        assert client.get("/api/rooms").json()["locked"] == ["dock"]
        with client.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({"type": "auth", "token": kim}))
            ws.receive_json()

            body = _catch(client, lun)
            assert body["seq"] is not None and body["balance"] == 800 + body["value"]
            assert body["deliverable"] == [{"room": "house_a", "name": "빈 집", "have": 0, "want": 2}]
            recv(ws, "money"), recv(ws, "fish")

            # somebody else's catch
            r = client.post("/api/deliver", json={"seq": body["seq"]}, headers=auth(kim))
            assert r.status_code == 403 and r.json()["error"] == "not_your_catch"
            # the wrong room
            r = client.post("/api/deliver", json={"seq": body["seq"], "room": "inn"}, headers=auth(lun))
            assert r.status_code == 400 and r.json()["error"] == "nothing_to_deliver"
            # the real thing: the money goes back out of the pool, the stage counts it
            r = client.post("/api/deliver", json={"seq": body["seq"]}, headers=auth(lun))
            assert r.status_code == 200, r.text
            assert r.json() == {"balance": 800, "room": "house_a", "have": 1, "want": 2, "completed": []}
            assert recv(ws, "money")["balance"] == 800
            ev = recv(ws, "event")["event"]
            assert ev["kind"] == "deliver" and ev["room_id"] == "house_a" and ev["amount"] == -body["value"] and ev["data"] == {"stage": 0, "kind": "fish"}
            # only once
            r = client.post("/api/deliver", json={"seq": body["seq"]}, headers=auth(lun))
            assert r.status_code == 400 and r.json()["error"] == "already_delivered"
            # unknown seq
            assert client.post("/api/deliver", json={"seq": 999}, headers=auth(lun)).json()["error"] == "not_found"

            # second catch: the window is over → expired, nothing counted
            body2 = _catch(client, lun)
            assert body2["deliverable"][0]["have"] == 1
            recv(ws, "money"), recv(ws, "fish")
            from app import config, db
            conn = db.connect(config.DB_PATH)
            conn.execute("UPDATE ledger SET ts = ts - 300 WHERE seq = ?", (body2["seq"],))
            conn.close()
            r = client.post("/api/deliver", json={"seq": body2["seq"]}, headers=auth(lun))
            assert r.status_code == 400 and r.json()["error"] == "deliver_expired"

            # third catch completes the stage: the dock opens for everyone
            body3 = _catch(client, lun)
            recv(ws, "money"), recv(ws, "fish")
            r = client.post("/api/deliver", json={"seq": body3["seq"]}, headers=auth(lun))
            assert r.status_code == 200 and r.json()["have"] == 2 and r.json()["completed"] == [{"room": "house_a", "stage": "fish", "name": "낚시"}]
            recv(ws, "money")
            assert recv(ws, "event")["event"]["kind"] == "deliver"
            assert recv(ws, "event")["event"]["kind"] == "stage"
            prog = recv(ws, "progress")
            assert prog["locked"] == [] and prog["rooms"]["house_a"]["done"] is True
        assert client.get("/api/rooms").json()["locked"] == []
        # a catch after the stage is done has nowhere to go
        body4 = _catch(client, lun)
        assert body4["deliverable"] == []
        assert client.post("/api/deliver", json={"seq": body4["seq"]}, headers=auth(lun)).json()["error"] == "nothing_to_deliver"
        # pool: 800 + 4 catches - 2 delivered
        assert client.get("/api/me", headers=auth(lun)).json()["balance"] == 800 + body2["value"] + body4["value"]
