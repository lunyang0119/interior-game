"""Phase 4: server-scheduled bites, client-reported holds (pulls), reward into the shared pool."""
import json
import random
import time

from app.fishing import HoldSpan
from conftest import auth, recv, register


def _wait_until_judgeable(cast):
    last = cast["bites"][-1]
    time.sleep((last["at_ms"] + last["window_ms"] + last["hold_ms"]) / 1000 + 0.05)


def _holds(cast, n):
    """A full hold started in the middle of each of the first n bites."""
    out = []
    for b in cast["bites"][:n]:
        t = b["at_ms"] + b["window_ms"] // 2
        out.append({"start_ms": t, "end_ms": t + b["hold_ms"]})
    return out


def _finish(client, token, cast, holds, **extra):
    return client.post("/api/fish/finish", json={"session": cast["session"], "holds": holds, **extra}, headers=auth(token))


def test_start_gives_schedule(client):
    lun = register(client, "lun")
    assert client.post("/api/fish/start").status_code == 401
    r = client.post("/api/fish/start", headers=auth(lun))
    assert r.status_code == 200, r.text
    cast = r.json()
    assert [b["at_ms"] for b in cast["bites"]] == [100, 500, 900]  # gap 100 + window 200 + hold 100
    assert all(b["hold_ms"] == 100 for b in cast["bites"]) and "real" not in json.dumps(cast)
    info = client.get("/api/fish").json()
    assert [l["id"] for l in info["loot"]] == ["anchovy", "chest"] and "weight" not in json.dumps(info)


def test_judge_counts_pulls_and_escapes(client):
    fishing = client.app.state.fishing
    s = fishing.start("lun")
    def hold(t, ms=100):
        return HoldSpan(t, t + ms)
    mid = [b.at_ms + b.window_ms // 2 for b in s.bites]  # 200, 600, 1000
    full = [hold(t) for t in mid]
    assert fishing.judge(s, full) == (3, False)
    assert fishing.judge(s, full[:2]) == (2, False)            # never pressed on the last bite: fewer pulls, no escape
    assert fishing.judge(s, [full[0], full[2]]) == (2, False)
    assert fishing.judge(s, []) == (0, False)
    assert fishing.judge(s, [hold(mid[0], 30)] + full[1:]) == (2, False)  # let go too soon: that bite is lost
    assert fishing.judge(s, [hold(mid[0], 60)] + full[1:]) == (3, False)  # 100 - slack 50 still counts
    assert fishing.judge(s, [hold(30)] + full) == (0, True)    # pressed before any bite
    assert fishing.judge(s, [full[0], hold(mid[0] + 10), full[1]]) == (1, True)  # second press on the same bite
    assert fishing.judge(s, [full[0], hold(400)]) == (1, True)  # between bites (windows 100..300 and 500..700, slack 50)


def test_three_pulls_pay_the_pool_and_tell_everyone(client):
    lun = register(client, "lun")
    kim = register(client, "kim")
    with client.websocket_connect("/ws") as k:
        k.send_text(json.dumps({"type": "auth", "token": kim}))
        k.receive_json()
        cast = client.post("/api/fish/start", headers=auth(lun)).json()
        _wait_until_judgeable(cast)
        r = _finish(client, lun, cast, _holds(cast, 3))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True and body["pulls"] == 3 and body["balance"] == 800 + body["value"]
        money = recv(k, "money")
        assert money == {"type": "money", "balance": 800 + body["value"]}
        fish = recv(k, "fish")
        assert fish["type"] == "fish" and fish["id"] == "lun" and fish["loot"] == body["id"] and fish["value"] == body["value"]
        ev = recv(k, "event")["event"]
        assert ev["kind"] == "fish" and ev["item_id"] == body["id"] and ev["amount"] == body["value"]
        # no stage wants fish in this catalog → nothing to deliver, the money stays
        assert body["seq"] is not None and body["deliverable"] == []
        r = client.post("/api/deliver", json={"seq": body["seq"]}, headers=auth(lun))
        assert r.status_code == 400 and r.json()["error"] == "nothing_to_deliver"
    assert client.get("/api/me", headers=auth(lun)).json()["balance"] == 800 + body["value"]
    # the session is spent
    r = _finish(client, lun, cast, _holds(cast, 3))
    assert r.status_code == 400 and r.json()["error"] == "no_session"


def test_catch_chance_by_pulls(client):
    lun = register(client, "lun")
    fishing = client.app.state.fishing
    fishing.rng = random.Random(3)
    results = {}
    for pulls in (1, 2, 2, 2, 2, 2, 2, 2, 2):
        cast = client.post("/api/fish/start", headers=auth(lun)).json()
        _wait_until_judgeable(cast)
        body = _finish(client, lun, cast, _holds(cast, pulls)).json()
        assert body["pulls"] == pulls and body["escaped"] is False
        results.setdefault(pulls, []).append(body["ok"])
    assert results[1] == [False]
    assert True in results[2] and False in results[2]  # 50%


def test_escape_and_early_finish_never_pay(client):
    lun = register(client, "lun")
    # three good pulls, but the client says the fish ran off
    cast = client.post("/api/fish/start", headers=auth(lun)).json()
    _wait_until_judgeable(cast)
    body = _finish(client, lun, cast, _holds(cast, 3), escaped=True).json()
    assert body["ok"] is False and body["escaped"] is True
    # a tap before the first bite
    cast = client.post("/api/fish/start", headers=auth(lun)).json()
    _wait_until_judgeable(cast)
    body = _finish(client, lun, cast, [{"start_ms": 10, "end_ms": 50}] + _holds(cast, 3)).json()
    assert body["ok"] is False and body["escaped"] is True
    # finishing before the last bite is over counts as an escape
    cast = client.post("/api/fish/start", headers=auth(lun)).json()
    body = _finish(client, lun, cast, _holds(cast, 3)).json()
    assert body["ok"] is False and body["escaped"] is True
    assert client.get("/api/me", headers=auth(lun)).json()["balance"] == 800


def test_bad_session(client):
    lun = register(client, "lun")
    kim = register(client, "kim")
    cast = client.post("/api/fish/start", headers=auth(lun)).json()
    r = _finish(client, kim, cast, [])
    assert r.status_code == 400 and r.json()["error"] == "no_session"  # not kim's cast
    r = client.post("/api/fish/finish", json={"session": "nope", "holds": []}, headers=auth(lun))
    assert r.status_code == 400 and r.json()["error"] == "no_session"
    # a new cast abandons the old one
    cast2 = client.post("/api/fish/start", headers=auth(lun)).json()
    _wait_until_judgeable(cast2)
    assert _finish(client, lun, cast, []).json()["error"] == "no_session"
    assert _finish(client, lun, cast2, []).status_code == 200


def test_cooldown(client):
    lun = register(client, "lun")
    client.app.state.fishing.cfg.cooldown_s = 60
    cast = client.post("/api/fish/start", headers=auth(lun)).json()
    _wait_until_judgeable(cast)
    _finish(client, lun, cast, [])
    r = client.post("/api/fish/start", headers=auth(lun))
    assert r.status_code == 429 and r.json()["error"] == "fish_cooldown"


def test_zero_value_loot_is_allowed(env):
    """A dud (value 0) is a legal catch: it loads, and it never touches the ledger."""
    import json as _json
    from app import fishing as fm
    cfg = _json.loads((env["data"] / "fishing.json").read_text(encoding="utf-8"))
    cfg["loot"].append({"id": "dud", "name": "꽝", "value": 0, "weight": 1})
    (env["data"] / "fishing.json").write_text(_json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    loaded = fm.load_config()
    assert [l.value for l in loaded.loot][-1] == 0
