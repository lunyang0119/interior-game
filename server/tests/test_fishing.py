"""Phase 4: server-scheduled bites, client-reported holds, reward into the shared pool."""
import json
import random
import time

from conftest import auth, register


def _seed_rng(client, seed=7):
    client.app.state.fishing.rng = random.Random(seed)


def _wait_until_judgeable(cast):
    real = next(b for b in cast["bites"] if b["real"])
    time.sleep((real["at_ms"] + real["window_ms"]) / 1000 + 0.05)
    return real


def test_start_gives_schedule(client):
    lun = register(client, "lun")
    assert client.post("/api/fish/start").status_code == 401
    r = client.post("/api/fish/start", headers=auth(lun))
    assert r.status_code == 200, r.text
    cast = r.json()
    assert len(cast["bites"]) == 3 and sum(b["real"] for b in cast["bites"]) == 1
    assert cast["hold_ms"] in (105, 300)  # anchovy 100+5 / chest 100+200 (max 500)
    assert cast["bites"][0]["at_ms"] == 100 and cast["bites"][1]["at_ms"] == 400  # gap 100 + window 200
    info = client.get("/api/fish").json()
    assert [l["id"] for l in info["loot"]] == ["anchovy", "chest"] and "weight" not in json.dumps(info)


def test_catch_pays_the_pool_and_tells_everyone(client):
    lun = register(client, "lun")
    kim = register(client, "kim")
    with client.websocket_connect("/ws") as k:
        k.send_text(json.dumps({"type": "auth", "token": kim}))
        k.receive_json()
        cast = client.post("/api/fish/start", headers=auth(lun)).json()
        real = _wait_until_judgeable(cast)
        hold = {"start_ms": real["at_ms"] + 20, "end_ms": real["at_ms"] + 20 + cast["hold_ms"]}
        r = client.post("/api/fish/finish", json={"session": cast["session"], "holds": [hold]}, headers=auth(lun))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True and body["balance"] == 800 + body["value"]
        money = k.receive_json()
        assert money == {"type": "money", "balance": 800 + body["value"]}
        fish = k.receive_json()
        assert fish["type"] == "fish" and fish["id"] == "lun" and fish["loot"] == body["id"] and fish["value"] == body["value"]
    assert client.get("/api/me", headers=auth(lun)).json()["balance"] == 800 + body["value"]
    # the session is spent
    r = client.post("/api/fish/finish", json={"session": cast["session"], "holds": [hold]}, headers=auth(lun))
    assert r.status_code == 400 and r.json()["error"] == "no_session"


def test_miss_too_short_wrong_bite_and_scared(client):
    lun = register(client, "lun")
    # too short a hold
    cast = client.post("/api/fish/start", headers=auth(lun)).json()
    real = _wait_until_judgeable(cast)
    r = client.post("/api/fish/finish", json={"session": cast["session"], "holds": [{"start_ms": real["at_ms"], "end_ms": real["at_ms"] + cast["hold_ms"] - 30}]}, headers=auth(lun))
    assert r.json()["ok"] is False and r.json()["balance"] == 800 and r.json()["name"] in ("멸치", "보물상자")
    # held on a fake nibble (scares the fish) even though the real one was held too
    cast = client.post("/api/fish/start", headers=auth(lun)).json()
    real = _wait_until_judgeable(cast)
    fake = next(b for b in cast["bites"] if not b["real"])
    holds = [{"start_ms": fake["at_ms"], "end_ms": fake["at_ms"] + 50}, {"start_ms": real["at_ms"], "end_ms": real["at_ms"] + cast["hold_ms"]}]
    assert client.post("/api/fish/finish", json={"session": cast["session"], "holds": holds}, headers=auth(lun)).json()["ok"] is False
    # no holds at all
    cast = client.post("/api/fish/start", headers=auth(lun)).json()
    _wait_until_judgeable(cast)
    assert client.post("/api/fish/finish", json={"session": cast["session"], "holds": []}, headers=auth(lun)).json()["ok"] is False
    assert client.get("/api/me", headers=auth(lun)).json()["balance"] == 800


def test_finish_too_early_and_bad_session(client):
    lun = register(client, "lun")
    kim = register(client, "kim")
    cast = client.post("/api/fish/start", headers=auth(lun)).json()
    r = client.post("/api/fish/finish", json={"session": cast["session"], "holds": []}, headers=auth(lun))
    assert r.status_code == 400 and r.json()["error"] == "too_early"
    r = client.post("/api/fish/finish", json={"session": cast["session"], "holds": []}, headers=auth(kim))
    assert r.status_code == 400 and r.json()["error"] == "no_session"  # not kim's cast
    r = client.post("/api/fish/finish", json={"session": "nope", "holds": []}, headers=auth(lun))
    assert r.status_code == 400 and r.json()["error"] == "no_session"
    # a new cast abandons the old one
    cast2 = client.post("/api/fish/start", headers=auth(lun)).json()
    _wait_until_judgeable(cast2)
    assert client.post("/api/fish/finish", json={"session": cast["session"], "holds": []}, headers=auth(lun)).json()["error"] == "no_session"
    assert client.post("/api/fish/finish", json={"session": cast2["session"], "holds": []}, headers=auth(lun)).status_code == 200


def test_cooldown(client):
    lun = register(client, "lun")
    client.app.state.fishing.cfg.cooldown_s = 60
    cast = client.post("/api/fish/start", headers=auth(lun)).json()
    _wait_until_judgeable(cast)
    client.post("/api/fish/finish", json={"session": cast["session"], "holds": []}, headers=auth(lun))
    r = client.post("/api/fish/start", headers=auth(lun))
    assert r.status_code == 429 and r.json()["error"] == "fish_cooldown"
