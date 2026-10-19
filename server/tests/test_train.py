"""Train (fugitive) minigame: role filtering, vote rules, timer restore, pause/resume, no sheet leak, engine copy."""

import hashlib
from contextlib import ExitStack, contextmanager
import json
import sqlite3
import time
import types
from pathlib import Path

import pytest

from conftest import auth, register

SECRET = "train-secret"
# anything about the fugitive that must never reach a hunter/spectator client
FORBIDDEN_KEYS = {"fugitive", "fugitive_path", "position_history", "hidden_events", "seed", "ram", "traced_at",
                  "hidden_until", "hacks", "hacks_disabled", "log", "log_entry", "admin_id", "hunters_full",
                  "fugitive_order", "fugitive_room_before", "fugitive_room_after", "lockable_edges", "reachable",
                  "bot_reasons", "route"}


def keys_of(obj, acc=None):
    acc = set() if acc is None else acc
    if isinstance(obj, dict):
        for k, v in obj.items():
            acc.add(k)
            keys_of(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            keys_of(v, acc)
    return acc


def assert_hunter_safe(payload):
    bad = keys_of(payload) & FORBIDDEN_KEYS
    assert not bad, f"fugitive data leaked to a hunter payload: {sorted(bad)}"
    assert "sheet" not in json.dumps(payload, ensure_ascii=False).lower()


@contextmanager
def ws_auth(client, token, path="/ws/train"):
    with client.websocket_connect(path) as ws:
        ws.send_json({"type": "auth", "token": token})
        yield ws


def recv(ws, kind, skip=("state", "submitted", "vote", "deadline", "round_open", "hunter_order", "fugitive_submitted",
                          "bot_thinking")):
    kinds = (kind,) if isinstance(kind, str) else kind
    while True:
        m = ws.receive_json()
        if m["type"] in kinds:
            return m
        assert m["type"] in skip, f"expected {kind}, got {m['type']}"


def setup(client, hunters=("h1", "h2"), hunter_count=None, overrides=None):
    """'adm' opens a lobby (no secret: the opener becomes the fugitive), hunters join, the game starts. Returns tokens."""
    tok = {"adm": register(client, "adm")}
    for h in hunters:
        tok[h] = register(client, h)
    body = {"hunter_count": hunter_count or len(hunters)}
    if overrides:
        body["overrides"] = overrides
    r = client.post("/api/train/game", json=body, headers=auth(tok["adm"]))
    assert r.status_code == 200, r.text
    for h in hunters:
        assert client.post("/api/train/join", headers=auth(tok[h])).status_code == 200
    r = client.post("/api/train/start", headers=auth(tok["adm"]))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ROUND_OPEN"
    return tok


def state(client, token):
    r = client.get("/api/train/state", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def mgr(client):
    return client.app.state.train


def wait_for(cond, timeout=2.0):
    """The webhook runs as a background task on the server loop: give it a moment."""
    import time
    end = time.time() + timeout
    while not cond() and time.time() < end:
        time.sleep(0.02)
    assert cond()


@pytest.fixture()
def stack():
    with ExitStack() as st:
        yield st


# ---------------------------------------------------------------------------
# claim / lobby
# ---------------------------------------------------------------------------
def test_claim_requires_secret_and_rebinds(client):
    a, b = register(client, "a"), register(client, "b")
    assert client.post("/api/train/claim", json={"secret": "nope"}, headers=auth(a)).status_code == 403
    assert client.post("/api/train/claim", json={"secret": SECRET}, headers=auth(a)).json()["role"] == "fugitive"
    assert state(client, a)["role"] == "fugitive"
    assert state(client, b)["role"] == "spectator"
    # another account claiming replaces the binding (register reissues tokens by nickname, so the secret is the gate)
    assert client.post("/api/train/claim", json={"secret": SECRET}, headers=auth(b)).status_code == 200
    assert state(client, a)["role"] == "spectator"
    assert state(client, b)["role"] == "fugitive"
    # the binding survives a restart (train_meta)
    assert mgr(client).admin_id == "b"


def test_claim_disabled_without_secret(client, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "TRAIN_ADMIN_SECRET", "")
    a = register(client, "a")
    assert client.post("/api/train/claim", json={"secret": "x"}, headers=auth(a)).json()["error"] == "train_disabled"


def test_lobby_rules(client):
    adm, h1, h2, h3 = (register(client, x) for x in ("adm", "h1", "h2", "h3"))
    # anyone opens a game and becomes its fugitive/admin — persisted, so a restart keeps the binding
    assert client.get("/api/train/state", headers=auth(adm)).json()["role"] == "spectator"
    r = client.post("/api/train/game", json={"hunter_count": 2}, headers=auth(adm))
    assert r.json()["status"] == "LOBBY" and r.json()["map_id"] == "car2077_9"  # scaling_web picks the map
    assert r.json()["role"] == "fugitive" and mgr(client).admin_id == "adm"
    from app.train import store
    assert store.load_admin() == "adm"
    assert client.post("/api/train/start", headers=auth(h1)).json()["error"] == "not_admin"  # others stay spectators
    assert client.post("/api/train/join", headers=auth(adm)).json()["error"] == "is_admin"
    assert client.post("/api/train/start", headers=auth(adm)).json()["error"] == "not_enough_hunters"
    client.post("/api/train/join", headers=auth(h1))
    client.post("/api/train/join", headers=auth(h2))
    assert client.post("/api/train/join", headers=auth(h3)).json()["error"] == "lobby_full"
    assert client.post("/api/train/game", json={"hunter_count": 2}, headers=auth(adm)).json()["error"] == "game_active"
    st = client.post("/api/train/start", headers=auth(adm)).json()
    assert st["status"] == "ROUND_OPEN" and st["round_no"] == 1
    assert st["config"]["round_timer_sec"] == 3600 and st["config"]["early_resolve"] is True  # web defaults
    assert client.post("/api/train/join", headers=auth(h3)).status_code == 409
    assert state(client, h3)["role"] == "spectator"


# ---------------------------------------------------------------------------
# role filtering
# ---------------------------------------------------------------------------
def test_hunter_rest_payload_has_no_fugitive_fields(client):
    tok = setup(client)
    for who in ("h1", "h2"):
        s = state(client, tok[who])
        assert s["role"] == "hunter" and s["you"]["id"] == who
        assert set(s["avatars"]) == {"h1", "h2"} and "skin" in s["avatars"]["h1"]
        assert_hunter_safe(s)
        assert s["view"]["capture_room"] is None
    # fugitive sees the truth
    f = state(client, tok["adm"])
    assert f["role"] == "fugitive" and f["fugitive"]["room"] and f["fugitive"]["ram"] > 0
    assert set(f["hacks"]) == {"ping", "doorlock", "distract", "blackout", "hide", "overload"}
    assert f["position_history"] == [f["fugitive"]["room"]]


def test_round_resolved_payloads_are_role_filtered(client, stack):
    tok = setup(client)
    h1 = stack.enter_context(ws_auth(client, tok["h1"]))
    adm = stack.enter_context(ws_auth(client, tok["adm"]))
    hello = recv(h1, "hello")
    assert hello["role"] == "hunter"
    assert_hunter_safe(hello["state"])
    assert recv(adm, "hello")["role"] == "fugitive"
    # everyone submits → early resolve
    f = state(client, tok["adm"])
    move = f["reachable"][0]
    assert client.post("/api/train/fugitive/order", json={"move": move}, headers=auth(tok["adm"])).status_code == 200
    assert client.post("/api/train/order", json={"type": "scan"}, headers=auth(tok["h1"])).status_code == 200
    assert client.post("/api/train/order", json={"type": "stay"}, headers=auth(tok["h2"])).status_code == 200
    m = recv(h1, "round_resolved")
    assert m["report"]["round"] == 1
    assert "fugitive_path" not in m["report"]["playback"]
    assert m["report"]["playback"]["hunters"]
    assert_hunter_safe(m)
    a = recv(adm, "round_resolved")
    assert a["report"]["playback"]["fugitive_path"][0] == f["fugitive"]["room"]
    assert a["log_entry"]["seed"] == a["state"]["log"][-1]["seed"]
    assert a["state"]["fugitive"]["room"] == a["report"]["playback"]["fugitive_path"][-1]
    assert recv(h1, "round_open")["round"] == 2


def test_hunter_orders_public_but_fugitive_needs_ping(client, stack):
    tok = setup(client, hunters=("h1", "h2", "h3"))
    h2 = stack.enter_context(ws_auth(client, tok["h2"]))
    adm = stack.enter_context(ws_auth(client, tok["adm"]))
    recv(h2, "hello")
    recv(adm, "hello")
    me = state(client, tok["h1"])["you"]["room"]
    rooms = {r["room"]: r for r in state(client, tok["h1"])["view"]["map_rows"]}
    dest = rooms[me]["neighbors"].split(",")[0]
    r = client.post("/api/train/order", json={"type": "move", "target": dest}, headers=auth(tok["h1"]))
    assert r.status_code == 200, r.text
    # hunters and spectators see the destination
    m = recv(h2, "submitted", skip=())
    assert m == {"type": "submitted", "id": "h1", "submitted": True, "round": 1, "order": {"type": "move", "target": dest}}
    assert state(client, tok["h2"])["orders"]["h1"] == {"type": "move", "target": dest}
    # the fugitive only gets the flag until they ping
    m = recv(adm, "submitted", skip=())
    assert m == {"type": "submitted", "id": "h1", "submitted": True, "round": 1}
    f = state(client, tok["adm"])
    assert f["orders"]["h1"] is None and f["hunters_full"]["h1"]["order"] is None
    assert f["hunters_full"]["h1"]["submitted"] is True and f["fugitive"]["pinged"] is False
    r = client.post("/api/train/fugitive/ping", headers=auth(tok["adm"]))
    assert r.status_code == 200, r.text
    assert r.json()["orders"]["h1"] == {"type": "move", "target": dest} and r.json()["orders"]["h2"] is None
    f = state(client, tok["adm"])
    assert f["fugitive"]["pinged"] is True and f["hunters_full"]["h1"]["order"] == {"type": "move", "target": dest}
    # post-ping stream: later submits reach the fugitive with their content
    client.post("/api/train/order", json={"type": "search"}, headers=auth(tok["h2"]))
    m = recv(adm, "hunter_order", skip=("state",))
    assert m["id"] == "h2" and m["order"] == {"type": "search", "target": None}
    assert client.post("/api/train/fugitive/ping", headers=auth(tok["adm"])).status_code == 400  # once per round


def test_spectator_sees_public_view_only_and_cannot_act(client):
    tok = setup(client)
    spec = register(client, "spec")
    s = state(client, spec)
    assert s["role"] == "spectator" and s["you"]["room"] is None and s["view"]["hunters"]
    assert_hunter_safe(s)
    assert client.post("/api/train/order", json={"type": "stay"}, headers=auth(spec)).json()["error"] == "not_hunter"
    assert client.post("/api/train/fugitive/ping", headers=auth(spec)).json()["error"] == "not_admin"
    assert state(client, tok["h1"])["fugitive_submitted"] is False
    client.post("/api/train/fugitive/order", json={}, headers=auth(tok["adm"]))
    s2 = state(client, tok["h1"])
    assert s2["fugitive_submitted"] is True and "fugitive_order" not in json.dumps(s2)
    assert_hunter_safe(s2)
    assert client.post("/api/train/reveal", json={"on": True}, headers=auth(tok["adm"])).json()["error"] == "not_captured"
    assert "route" not in state(client, tok["h1"])
    assert client.get("/api/train/maps", headers=auth(spec)).json()["maps"][0]["id"] == "car2077_9"  # maps are public
    d = client.get("/api/train/maps/car2077_12", headers=auth(tok["adm"])).json()
    assert len(d["rooms"]) == 12 and {"id", "col", "row", "device", "neighbors"} <= set(d["rooms"][0])


def test_hunter_order_errors(client):
    tok = setup(client)
    r = client.post("/api/train/order", json={"type": "move", "target": "Z9"}, headers=auth(tok["h1"]))
    assert r.json()["error"] == "unknown_room"
    me = state(client, tok["h1"])["you"]["room"]
    far = next(r["room"] for r in state(client, tok["h1"])["view"]["map_rows"]
               if r["room"] != me and me not in r["neighbors"].split(","))
    assert client.post("/api/train/order", json={"type": "move", "target": far}, headers=auth(tok["h1"])).json()["error"] == "not_adjacent"
    # fugitive rule errors carry the engine's own message
    r = client.post("/api/train/fugitive/order", json={"move": "Z9"}, headers=auth(tok["adm"]))
    assert r.status_code == 400 and r.json()["error"] == "rule" and "Z9" in r.json()["message"]


# ---------------------------------------------------------------------------
# early resolve / grace / timer
# ---------------------------------------------------------------------------
def test_grace_then_fugitive_submit_resolves(client):
    tok = setup(client, overrides={"fugitive_grace_sec": 100})
    m = mgr(client)
    g = m.game
    client.post("/api/train/order", json={"type": "stay"}, headers=auth(tok["h1"]))
    assert g.policy.grace_until is None
    client.post("/api/train/order", json={"type": "stay"}, headers=auth(tok["h2"]))
    assert g.policy.grace_until is not None and g.policy.grace_until <= g.policy.deadline_ts
    assert state(client, tok["h1"])["grace_until"] == g.policy.grace_until
    assert g.engine.round_no == 1
    assert client.post("/api/train/fugitive/order", json={}, headers=auth(tok["adm"])).json()["resolved"] is True
    assert g.engine.round_no == 2 and g.policy.grace_until is None and g.status == "ROUND_OPEN"


def test_timer_expiry_resolves_with_timeout(client):
    tok = setup(client, overrides={"round_timer_sec": 100})
    m = mgr(client)
    g = m.game
    t0 = g.policy.round_open_ts
    client.post("/api/train/order", json={"type": "scan"}, headers=auth(tok["h1"]))
    m.now = lambda: t0 + 50
    assert client.portal.call(m.check_deadline) is False and g.engine.round_no == 1
    m.now = lambda: t0 + 101
    assert client.portal.call(m.check_deadline) is True
    assert g.engine.round_no == 2
    assert g.engine.log[-1]["report"]["timed_out"] is True
    assert g.engine.log[-1]["hunter_orders"]["h2"]["type"] == "stay"
    assert g.engine.log[-1]["hunter_orders"]["h1"]["type"] == "scan"
    assert g.policy.deadline_ts == t0 + 101 + 100 and m._timer is not None and not m._timer.done()


def test_restore_resolves_expired_round_on_boot(env):
    from fastapi.testclient import TestClient
    from app.main import create_app

    with TestClient(create_app()) as c:
        tok = setup(c, overrides={"round_timer_sec": 60})
        rid = mgr(c).game.row_id
    # the server went down and the deadline passed meanwhile
    conn = sqlite3.connect(env["data"].parent / "test.db")
    row = json.loads(conn.execute("SELECT state_json FROM train_games WHERE id = ?", (rid,)).fetchone()[0])
    row["policy"]["deadline_ts"] = 1.0
    conn.execute("UPDATE train_games SET state_json = ? WHERE id = ?", (json.dumps(row), rid))
    conn.commit()
    conn.close()
    with TestClient(create_app()) as c:
        m = mgr(c)
        assert m.admin_id == "adm"
        assert m.game.row_id == rid and m.game.engine.round_no == 2
        assert m.game.engine.log[-1]["report"]["timed_out"] is True
        assert m.game.policy.deadline_ts > 1.0 and m._timer is not None
        assert state(c, tok["h1"])["round_no"] == 2


def test_restore_keeps_running_round(env):
    from fastapi.testclient import TestClient
    from app.main import create_app

    with TestClient(create_app()) as c:
        tok = setup(c)
        c.post("/api/train/order", json={"type": "scan"}, headers=auth(tok["h1"]))
        before = mgr(c).game.policy.deadline_ts
    with TestClient(create_app()) as c:
        m = mgr(c)
        assert m.game.status == "ROUND_OPEN" and m.game.engine.round_no == 1
        assert m.game.policy.deadline_ts == before and m._timer is not None
        assert m.game.engine.hunters["h1"].order.type == "scan"
        assert state(c, tok["h1"])["you"]["order"] == {"type": "scan", "target": None}


# ---------------------------------------------------------------------------
# pause / resume / extend
# ---------------------------------------------------------------------------
def test_pause_resume_shifts_clock(client):
    tok = setup(client, overrides={"round_timer_sec": 1000, "vote_skip_after_sec": 300})
    m = mgr(client)
    g = m.game
    t0 = g.policy.round_open_ts
    m.now = lambda: t0 + 100
    r = client.post("/api/train/pause", headers=auth(tok["adm"]))
    assert r.json()["paused_remaining"] == 900 and g.status == "PAUSED" and m._timer is None
    assert client.post("/api/train/order", json={"type": "stay"}, headers=auth(tok["h1"])).json()["error"] == "paused"
    assert client.post("/api/train/vote", json={"target": "h2"}, headers=auth(tok["h1"])).json()["error"] == "paused"
    client.post("/api/train/extend", json={"sec": 100}, headers=auth(tok["adm"]))
    assert g.policy.paused_remaining == 1000
    m.now = lambda: t0 + 600  # paused for 500s
    r = client.post("/api/train/resume", headers=auth(tok["adm"]))
    assert r.json()["deadline_ts"] == t0 + 1600 and g.status == "ROUND_OPEN" and m._timer is not None
    assert g.vote_after_ts() == t0 + 500 + 300  # the vote window also moved by the pause
    client.post("/api/train/extend", json={"sec": 50}, headers=auth(tok["adm"]))
    assert g.policy.deadline_ts == t0 + 1650


def test_resume_restarts_grace_when_crew_is_in(client):
    tok = setup(client, overrides={"round_timer_sec": 1000, "fugitive_grace_sec": 100})
    m = mgr(client)
    g = m.game
    for h in ("h1", "h2"):
        client.post("/api/train/order", json={"type": "stay"}, headers=auth(tok[h]))
    assert g.policy.grace_until is not None
    client.post("/api/train/pause", headers=auth(tok["adm"]))
    assert g.policy.grace_until is None
    client.post("/api/train/resume", headers=auth(tok["adm"]))
    assert g.status == "ROUND_OPEN" and g.engine.round_no == 1
    assert g.policy.grace_until is not None and g.policy.grace_until <= m.now() + 100
    # ...and when the fugitive had already submitted, resuming resolves at once
    client.post("/api/train/fugitive/order", json={}, headers=auth(tok["adm"]))
    assert g.engine.round_no == 2
    for h in ("h1", "h2"):
        client.post("/api/train/order", json={"type": "stay"}, headers=auth(tok[h]))
    client.post("/api/train/pause", headers=auth(tok["adm"]))
    client.post("/api/train/resume", headers=auth(tok["adm"]))
    assert g.engine.round_no == 2 and g.policy.grace_until is not None


def test_state_carries_recent_public_reports(client):
    tok = setup(client)
    assert state(client, tok["h1"])["reports"] == []
    for _ in range(2):
        for h in ("h1", "h2"):
            client.post("/api/train/order", json={"type": "stay"}, headers=auth(tok[h]))
        client.post("/api/train/fugitive/order", json={}, headers=auth(tok["adm"]))
    st = state(client, tok["h1"])
    assert [r["round"] for r in st["reports"]] == [1, 2] and st["reports"][-1] == st["report"]
    assert_hunter_safe(st)
    assert [r["round"] for r in state(client, tok["adm"])["reports"]] == [1, 2]


def test_paused_game_restores_without_timer(env):
    from fastapi.testclient import TestClient
    from app.main import create_app

    with TestClient(create_app()) as c:
        tok = setup(c)
        c.post("/api/train/pause", headers=auth(tok["adm"]))
        rem = mgr(c).game.policy.paused_remaining
    with TestClient(create_app()) as c:
        m = mgr(c)
        assert m.game.status == "PAUSED" and m._timer is None
        assert m.game.policy.paused_remaining == rem
        s = state(c, tok["h1"])
        assert s["status"] == "PAUSED" and s["paused_remaining"] == rem
        assert_hunter_safe(s)


# ---------------------------------------------------------------------------
# vote to skip
# ---------------------------------------------------------------------------
def test_vote_rules_two_hunters(client):
    tok = setup(client, overrides={"vote_skip_after_sec": 600})
    m = mgr(client)
    g = m.game
    t0 = g.policy.round_open_ts
    assert client.post("/api/train/vote", json={"target": "h2"}, headers=auth(tok["h1"])).json()["error"] == "vote_too_early"
    m.now = lambda: t0 + 601
    assert client.post("/api/train/vote", json={"target": "h1"}, headers=auth(tok["h1"])).json()["error"] == "vote_bad_target"
    assert client.post("/api/train/vote", json={"target": "adm"}, headers=auth(tok["h1"])).json()["error"] == "vote_bad_target"
    assert client.post("/api/train/vote", json={"target": "h2"}, headers=auth(tok["adm"])).json()["error"] == "not_hunter"
    # 2 hunters → 1 vote passes and the target is submitted as "stay" (the voter h1 has not submitted: no grace yet)
    r = client.post("/api/train/vote", json={"target": "h2"}, headers=auth(tok["h1"]))
    assert r.json() == {"votes": ["h1"], "need": 1, "passed": True}
    assert g.engine.hunters["h2"].order.type == "stay" and g.policy.grace_until is None
    assert client.post("/api/train/vote", json={"target": "h2"}, headers=auth(tok["h1"])).json()["error"] == "vote_bad_target"
    # the voted hunter cannot take the stay back or overwrite it this round (F40)
    assert client.delete("/api/train/order", headers=auth(tok["h2"])).json()["error"] == "voted_stay"
    assert client.post("/api/train/order", json={"type": "search"}, headers=auth(tok["h2"])).json()["error"] == "voted_stay"
    assert g.engine.hunters["h2"].order.type == "stay"


def test_vote_majority_void_and_reset(client, stack):
    tok = setup(client, hunters=("h1", "h2", "h3", "h4"), overrides={"vote_skip_after_sec": 0})
    m = mgr(client)
    g = m.game
    m.now = lambda: g.policy.round_open_ts + 1
    h4 = stack.enter_context(ws_auth(client, tok["h4"]))
    recv(h4, "hello")
    r = client.post("/api/train/vote", json={"target": "h3"}, headers=auth(tok["h1"]))
    assert r.json() == {"votes": ["h1"], "need": 2, "passed": False}
    assert recv(h4, "vote", skip=()) == {"type": "vote", "target": "h3", "voters": ["h1"], "need": 2, "passed": False}
    assert state(client, tok["h2"])["votes"] == {"h3": ["h1"]}
    # the target submits first → the vote is void
    client.post("/api/train/order", json={"type": "stay"}, headers=auth(tok["h3"]))
    assert g.policy.votes == {}
    v = recv(h4, "vote", skip=())
    assert v["target"] == "h3" and v["voters"] == [] and v.get("void") is True
    # majority of the OTHER hunters: 4 hunters → 2 votes
    client.post("/api/train/vote", json={"target": "h4"}, headers=auth(tok["h1"]))
    r = client.post("/api/train/vote", json={"target": "h4"}, headers=auth(tok["h2"]))
    assert r.json()["passed"] is True and g.engine.hunters["h4"].order.type == "stay"
    # votes reset with the next round
    g.policy.votes = {"h1": ["h2"]}
    client.post("/api/train/round/end", headers=auth(tok["adm"]))
    assert g.engine.round_no == 2 and g.policy.votes == {}


# ---------------------------------------------------------------------------
# capture, webhook, end game
# ---------------------------------------------------------------------------
def test_capture_broadcast_webhook_and_new_game(client, stack):
    tok = setup(client, overrides={"capture_mode": "search"})
    m = mgr(client)
    lines = []

    async def fake_hook(line):
        lines.append(line)

    m.webhook = fake_hook
    g = m.game
    # put the fugitive in h1's room so a search captures (test-only state poke; the engine resolves it)
    g.engine.fugitive.room = g.engine.hunters["h1"].room
    g.engine.position_history[-1] = g.engine.fugitive.room
    h2 = stack.enter_context(ws_auth(client, tok["h2"]))
    recv(h2, "hello")
    client.post("/api/train/order", json={"type": "search"}, headers=auth(tok["h1"]))
    client.post("/api/train/order", json={"type": "stay"}, headers=auth(tok["h2"]))
    client.post("/api/train/fugitive/order", json={}, headers=auth(tok["adm"]))
    rr = recv(h2, "round_resolved")
    assert rr["report"]["captured_by"] == "h1" and rr["report"]["capture_how"] == "search"
    assert_hunter_safe(rr)
    cap = recv(h2, "captured", skip=("state", "round_open"))
    assert cap["by"] == "h1" and cap["line"] == "**수수께끼의 인영을 h1가 잡았다!**\n**Conflict Resolved.**"
    wait_for(lambda: lines == [cap["line"]])  # COMBAT_MODE_ON went out before this test swapped the hook
    wait_for(lambda: g.policy.webhook_sent is True)
    s = state(client, tok["h2"])
    assert s["status"] == "CAPTURED" and s["view"]["capture_room"] == g.engine.fugitive.room
    # the route reveal: off by default (nothing in hunter payloads), admin-only, and only while CAPTURED
    assert_hunter_safe(s)
    assert client.post("/api/train/reveal", json={"on": True}, headers=auth(tok["h2"])).json()["error"] == "not_admin"
    r = client.post("/api/train/reveal", json={"on": True}, headers=auth(tok["adm"]))
    assert r.status_code == 200
    s = state(client, tok["h2"])
    assert [x["round"] for x in s["route"]] == [1] and s["route"][0]["path"][-1] == g.engine.fugitive.room
    assert "fugitive_path" not in json.dumps(s["report"])   # the per-report secret stays stripped; only `route` opens
    r = client.post("/api/train/reveal", json={"on": False}, headers=auth(tok["adm"]))
    assert "route" not in state(client, tok["h2"])
    assert client.get("/api/train/help", headers=auth(tok["h2"])).json()["tutorial"].count("/이동") == 1
    assert client.post("/api/train/order", json={"type": "stay"}, headers=auth(tok["h2"])).status_code == 409
    # a new lobby may be opened over a captured game; it ends the old row
    r = client.post("/api/train/game", json={"hunter_count": 2}, headers=auth(tok["adm"]))
    assert r.json()["status"] == "LOBBY"
    for _ in range(6):   # the reveal toggles above pushed CAPTURED states first
        st = recv(h2, "state", skip=("ended",))["state"]
        if st["status"] == "LOBBY":
            break
    assert st["status"] == "LOBBY"


def test_failed_webhook_does_not_mark_sent(client):
    tok = setup(client, overrides={"capture_mode": "search"})
    m = mgr(client)

    async def broken_hook(_line):
        raise RuntimeError("discord down")

    m.webhook = broken_hook
    g = m.game
    g.engine.fugitive.room = g.engine.hunters["h1"].room
    client.post("/api/train/order", json={"type": "search"}, headers=auth(tok["h1"]))
    client.post("/api/train/order", json={"type": "stay"}, headers=auth(tok["h2"]))
    r = client.post("/api/train/fugitive/order", json={}, headers=auth(tok["adm"]))
    assert r.status_code == 200 and g.status == "CAPTURED"
    import time
    time.sleep(0.2)
    assert g.policy.webhook_sent is False  # a restart will try the capture line again


def test_start_posts_combat_mode_line(client, stack):
    adm, h1, h2 = (register(client, x) for x in ("adm", "h1", "h2"))
    m = mgr(client)
    lines = []

    async def fake_hook(line):
        lines.append(line)

    m.webhook = fake_hook
    client.post("/api/train/claim", json={"secret": SECRET}, headers=auth(adm))
    client.post("/api/train/game", json={"hunter_count": 2}, headers=auth(adm))
    client.post("/api/train/join", headers=auth(h1))
    client.post("/api/train/join", headers=auth(h2))
    ws = stack.enter_context(ws_auth(client, h1))
    recv(ws, "hello")
    client.post("/api/train/start", headers=auth(adm))
    assert recv(ws, "started", skip=("state",))["line"] == "Activating Combat Mode"
    wait_for(lambda: lines == ["Activating Combat Mode"])


def test_end_game_and_config(client):
    tok = setup(client)
    r = client.put("/api/train/config", json={"set": {"scan_budget": "2", "nope": 1}}, headers=auth(tok["adm"]))
    assert r.status_code == 400 and r.json()["error"] == "bad_config"
    base_scan = mgr(client).game.engine.config["scan_budget"]   # scaling layer value, not necessarily DEFAULTS
    r = client.put("/api/train/config", json={"set": {"scan_budget": "3"}}, headers=auth(tok["adm"]))
    assert r.json()["config"]["scan_budget"] == 3 and r.json()["overrides"] == {"scan_budget": 3}
    assert mgr(client).game.engine.config["scan_budget"] == 3
    assert client.put("/api/train/config", json={"map_id": "car2077_16"}, headers=auth(tok["adm"])).json()["error"] == "map_locked"
    assert client.get("/api/train/config", headers=auth(tok["h1"])).status_code == 403
    assert state(client, tok["h1"])["config"]["scan_budget"] == 3
    assert "ram_max" not in state(client, tok["h1"])["config"]
    # the test preset: three policy values in one PUT, then reset drops them all and restores the base values
    base = mgr(client).game.engine.config["round_timer_sec"]
    r = client.put("/api/train/config", json={"set": {"round_timer_sec": 120, "vote_skip_after_sec": 30, "fugitive_grace_sec": 30}}, headers=auth(tok["adm"]))
    assert set(r.json()["overrides"]) == {"scan_budget", "round_timer_sec", "vote_skip_after_sec", "fugitive_grace_sec"}
    assert mgr(client).game.engine.config["round_timer_sec"] == 120
    r = client.put("/api/train/config", json={"reset": True}, headers=auth(tok["adm"]))
    assert r.json()["overrides"] == {} and r.json()["config"]["round_timer_sec"] == base
    assert mgr(client).game.engine.config["scan_budget"] == base_scan
    r = client.post("/api/train/game/end", headers=auth(tok["adm"]))
    assert r.json()["status"] == "IDLE" and mgr(client).game is None
    assert state(client, tok["h1"])["status"] == "IDLE"
    assert client.get("/api/train/state", headers=auth(tok["h1"])).status_code == 200


def test_ws_rejects_bad_token_and_ignores_moves(client, stack):
    tok = setup(client)
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/train") as ws:
            ws.send_json({"type": "auth", "token": "bad"})
            ws.receive_json()
    ws = stack.enter_context(ws_auth(client, tok["h1"]))
    recv(ws, "hello")
    ws.send_json({"type": "move", "x": 1, "y": 2})
    ws.send_text("not json")
    ws.send_json({"type": "ping"})
    assert ws.receive_json() == {"type": "pong"}
    assert mgr(client).game.engine.hunters["h1"].room  # unchanged by anything the client sent


# ---------------------------------------------------------------------------
# engine copy integrity
# ---------------------------------------------------------------------------
class FakeGemini:
    """Stands in for google.genai.Client: `models.generate_content(...)` returns a fixed JSON decision."""

    def __init__(self, text: str):
        self.text = text
        self.models = self

    def generate_content(self, model, contents, config=None):
        if "침입자(도주자)입니다" in contents:      # the fugitive prompt (bot_player.build_fugitive_prompt)
            return types.SimpleNamespace(text=self.fugitive_text)
        assert "승무원" in contents and "도주자" not in contents.split("[현재 현황판]")[0]  # the hunter prompt is hunter-side only
        return types.SimpleNamespace(text=self.text)

    fugitive_text = '{"move": null, "hack": null, "target": null, "reason": "테스트 대기"}'


def test_ai_fugitive_mode(client):
    from app.train import bot_player as B
    adm, h1 = register(client, "adm"), register(client, "h1")
    assert client.post("/api/train/game", json={"hunter_count": 2, "fugitive_ai": True}, headers=auth(adm)).json()["error"] == "ai_unavailable"
    # a fresh Manager on every test app, so inject the fake before opening the game
    r = client.post("/api/train/game", json={"hunter_count": 2}, headers=auth(adm))
    assert r.status_code == 200 and r.json()["role"] == "fugitive" and r.json()["admin"] is True
    mgr(client).bot_player = B.GeminiPlayer(client=FakeGemini('{"order": "stay", "reason": "봇 대기"}'))
    r = client.post("/api/train/fugitive-ai", json={"on": True}, headers=auth(adm))
    assert r.json()["fugitive_ai"] is True and r.json()["role"] == "fugitive" and r.json()["admin"] is True   # watches as the fugitive
    # the admin keeps the controls; once they ride as a hunter they see nothing secret
    assert client.post("/api/train/join", headers=auth(adm)).json()["role"] == "hunter"
    assert client.post("/api/train/join", headers=auth(h1)).status_code == 200
    assert client.post("/api/train/start", headers=auth(adm)).status_code == 200
    st = state(client, adm)
    assert st["role"] == "hunter" and st["admin"] is True and "fugitive" not in st
    assert_hunter_safe(st)
    assert client.post("/api/train/fugitive/ping", headers=auth(adm)).json()["error"] == "fugitive_is_ai"
    assert client.post("/api/train/fugitive/order", json={"move": None}, headers=auth(adm)).json()["error"] == "fugitive_is_ai"
    # Gemini submits the fugitive's order in the background; once both hunters are in, the round resolves at once
    eng = mgr(client).game.engine
    wait_for(lambda: eng.fugitive.order is not None)
    assert eng.bot_reasons[-1]["uid"] == "fugitive" and eng.bot_reasons[-1]["reason"] == "테스트 대기"
    assert "ai_log" not in state(client, h1)
    assert client.post("/api/train/order", json={"type": "stay"}, headers=auth(h1)).status_code == 200
    assert client.post("/api/train/order", json={"type": "stay"}, headers=auth(adm)).status_code == 200
    assert state(client, h1)["round_no"] == 2
    # turning the AI off in a lobby pulls the admin out of the crew
    client.post("/api/train/game/end", headers=auth(adm))
    client.post("/api/train/game", json={"hunter_count": 2, "fugitive_ai": True}, headers=auth(adm))
    client.post("/api/train/join", headers=auth(adm))
    r = client.post("/api/train/fugitive-ai", json={"on": False}, headers=auth(adm))
    assert r.json()["lobby"] == [] and r.json()["role"] == "fugitive"
    assert client.post("/api/train/join", headers=auth(adm)).json()["error"] == "is_admin"


def test_ai_hunters_fill_the_lobby_and_submit(client):
    from app.train import bot_player as B
    adm, h1 = register(client, "adm"), register(client, "h1")
    assert client.post("/api/train/game", json={"hunter_count": 3}, headers=auth(adm)).status_code == 200
    # no GEMINI_API_KEY in tests → the buttons stay hidden and the endpoint refuses
    assert state(client, h1)["ai_available"] is False
    assert client.post("/api/train/bots", json={"target_count": 3}, headers=auth(adm)).json()["error"] == "ai_unavailable"
    mgr(client).bot_player = B.GeminiPlayer(client=FakeGemini('{"order": "search", "reason": "테스트 수색"}'))
    assert client.post("/api/train/join", headers=auth(h1)).status_code == 200
    assert client.post("/api/train/bots", json={"target_count": 3}, headers=auth(h1)).json()["error"] == "not_admin"
    r = client.post("/api/train/bots", json={"target_count": 6}, headers=auth(adm))   # clamped to hunter_count
    assert r.status_code == 200 and r.json()["lobby"] == ["h1", "bot:1", "bot:2"] and r.json()["ai_available"] is True
    assert client.post("/api/train/bots", json={"target_count": 3}, headers=auth(adm)).json()["error"] == "lobby_full"
    assert client.delete("/api/train/bots", headers=auth(adm)).json()["lobby"] == ["h1"]
    assert client.post("/api/train/bots", json={"target_count": 3}, headers=auth(adm)).json()["lobby"] == ["h1", "bot:1", "bot:2"]
    assert client.post("/api/train/start", headers=auth(adm)).status_code == 200
    # the bots decide in a background task right after the round opens
    for _ in range(100):
        st = state(client, h1)
        subs = {h["name"]: h["submitted"] for h in st["view"]["hunters"]}
        if subs["bot:1"] and subs["bot:2"]:
            break
        time.sleep(0.05)
    assert subs["bot:1"] and subs["bot:2"] and not subs["h1"]
    assert st["orders"]["bot:1"]["type"] == "search"          # bot orders are public like any hunter's
    assert_hunter_safe(st)                                     # ...but their reasons are not
    fs = state(client, adm)
    assert [r["order"] for r in fs["bot_reasons"]] == ["search", "search"] and fs["bot_reasons"][0]["reason"] == "테스트 수색"
    assert fs["avatars"]["bot:1"]["preset"] == 0
    assert client.delete("/api/train/bots", headers=auth(adm)).json()["error"] == "not_open"   # lobby only
    # h1 submits → everyone in → fugitive grace starts (early resolve path still works with bots)
    assert client.post("/api/train/order", json={"type": "stay"}, headers=auth(h1)).status_code == 200
    assert state(client, h1)["grace_until"] is not None


def test_engine_files_copied_unchanged():
    root = Path(__file__).resolve().parents[2]
    ref, dst = root / "reference", root / "server" / "app" / "train"
    if not ref.exists():
        pytest.skip("reference/ not checked out")
    for name in ("engine.py", "config.py", "strings.py", "sim.py", "bot_player.py", "render.py"):
        src = (ref / name).read_bytes().replace(b"\r\n", b"\n")
        copied = (dst / name).read_bytes().replace(b"\r\n", b"\n").split(b"\n", 1)
        assert copied[0].startswith(b"# Copied unchanged") and b"2182a11" in copied[0]
        assert hashlib.sha256(copied[1]).hexdigest() == hashlib.sha256(src).hexdigest(), name
    assert (dst / "scaling_web.json").read_bytes() == (ref / "scaling_web.json").read_bytes()


# ---------------------------------------------------------------------------
# review 2026-10-18 fixes (train_review_261018.md)
# ---------------------------------------------------------------------------
def put_fugitive(g, room):
    """Test-only state poke: move the fugitive (and the start of its history) to `room`."""
    g.engine.fugitive.room = room
    g.engine.position_history[-1] = room


def test_cancel_order_during_grace_drops_grace(client, stack):
    """F03: a hunter taking their order back ends the fugitive's grace; the round deadline rules again."""
    tok = setup(client, overrides={"fugitive_grace_sec": 100, "round_timer_sec": 1000})
    m = mgr(client)
    g = m.game
    h1 = stack.enter_context(ws_auth(client, tok["h1"]))
    recv(h1, "hello")
    for h in ("h1", "h2"):
        client.post("/api/train/order", json={"type": "stay"}, headers=auth(tok[h]))
    grace = g.policy.grace_until
    assert grace is not None and g.effective_deadline() == grace
    assert recv(h1, "deadline", skip=("submitted",))["reason"] == "grace"
    r = client.delete("/api/train/order", headers=auth(tok["h2"]))
    assert r.status_code == 200 and r.json() == {"order": None}
    assert g.policy.grace_until is None and g.effective_deadline() == g.policy.deadline_ts
    d = recv(h1, "deadline", skip=("submitted",))
    assert d["reason"] == "grace_cancel" and d["deadline_ts"] == g.policy.deadline_ts
    m.now = lambda: grace + 1
    assert client.portal.call(m.check_deadline) is False and g.engine.round_no == 1   # no timed-out resolve at the old grace
    # the fugitive cancelling their own order is allowed and keeps the round open
    client.post("/api/train/fugitive/order", json={}, headers=auth(tok["adm"]))
    assert client.delete("/api/train/fugitive/order", headers=auth(tok["adm"])).json() == {"order": None}


def test_extend_during_grace_moves_grace(client):
    """F08: +time while the fugitive's grace runs moves the effective deadline too."""
    tok = setup(client, overrides={"fugitive_grace_sec": 100, "round_timer_sec": 1000})
    g = mgr(client).game
    for h in ("h1", "h2"):
        client.post("/api/train/order", json={"type": "stay"}, headers=auth(tok[h]))
    grace, deadline = g.policy.grace_until, g.policy.deadline_ts
    r = client.post("/api/train/extend", json={"sec": 600}, headers=auth(tok["adm"]))
    assert r.json()["grace_until"] == grace + 600 and r.json()["deadline_ts"] == deadline + 600
    assert g.effective_deadline() == grace + 600


def test_claim_refused_while_a_chase_runs(client):
    """F11: /claim during a running game would leave the claimer as hunter AND fugitive."""
    tok = setup(client)
    r = client.post("/api/train/claim", json={"secret": SECRET}, headers=auth(tok["h1"]))
    assert r.status_code == 400 and r.json()["error"] == "game_running"
    assert mgr(client).admin_id == "adm"
    client.post("/api/train/pause", headers=auth(tok["adm"]))
    assert client.post("/api/train/claim", json={"secret": SECRET}, headers=auth(tok["h1"])).json()["error"] == "game_running"
    client.post("/api/train/game/end", headers=auth(tok["adm"]))
    assert client.post("/api/train/claim", json={"secret": SECRET}, headers=auth(tok["h1"])).status_code == 200


@pytest.mark.parametrize("key,value", [
    ("signal_bands", "1;3"), ("signal_bands", "3,1"), ("signal_bands", "2"), ("round_timer_sec", 0),
    ("round_timer_sec", 59), ("fugitive_grace_sec", -1), ("vote_skip_after_sec", -5), ("trace_passive", -50),
    ("scan_trace", -1), ("hide_trace", -10), ("doorlock_cost", -1), ("ram_max", 0), ("max_rounds", 0),
    ("overheat_rounds", -1), ("fugitive_start", "Z9"), ("hunter_spawn_rooms", "A1,Z9"), ("escape_on_freeze", "maybe"),
])
def test_bad_config_values_rejected(client, key, value):
    """F19/F20: nothing the engine or the timer cannot run with gets into a running game (or a lobby)."""
    tok = setup(client)
    g = mgr(client).game
    before = dict(g.engine.config)
    r = client.put("/api/train/config", json={"set": {key: value}}, headers=auth(tok["adm"]))
    assert r.status_code == 400 and r.json()["error"] == "bad_config", r.text
    assert g.engine.config == before and g.policy.overrides == {}
    client.post("/api/train/game/end", headers=auth(tok["adm"]))
    r = client.post("/api/train/game", json={"hunter_count": 2, "overrides": {key: value}}, headers=auth(tok["adm"]))
    assert r.status_code == 400 and r.json()["error"] == "bad_config"


def test_good_config_values_and_placement_keys_accepted(client):
    tok = setup(client)
    r = client.put("/api/train/config", json={"set": {"signal_bands": "1,2", "round_timer_sec": 60, "fugitive_start": "B2",
                                                      "hunter_spawn_rooms": "A1,C3", "escape_on_freeze": "off"}},
                   headers=auth(tok["adm"]))
    assert r.status_code == 200, r.text
    assert r.json()["config"]["escape_on_freeze"] is False and r.json()["defaults"]["escape_on_freeze"] is True


def test_ping_response_state_push_and_hack_guards(client, stack):
    """F28 ping refreshes the fugitive; F24 a ping that would starve a confirmed hack is refused; F23 hide + move is
    refused; F21 the order response carries the order."""
    tok = setup(client)
    g = mgr(client).game
    put_fugitive(g, "A3")   # light → blackout
    adm = stack.enter_context(ws_auth(client, tok["adm"]))
    recv(adm, "hello")
    r = client.post("/api/train/fugitive/order", json={"move": "A2", "hack": "hide"}, headers=auth(tok["adm"]))
    assert r.status_code == 400 and r.json()["error"] == "hide_no_move"
    r = client.post("/api/train/fugitive/order", json={"move": "A2", "hack": "blackout"}, headers=auth(tok["adm"]))
    assert r.status_code == 200 and r.json()["order"] == {"move": "A2", "hack": "blackout", "target": None}
    g.engine.fugitive.ram = int(g.engine.config["blackout_cost"])   # exactly enough for the hack, not for a ping too
    r = client.post("/api/train/fugitive/ping", headers=auth(tok["adm"]))
    assert r.status_code == 400 and r.json()["error"] == "ping_breaks_hack"
    assert g.engine.fugitive.ping_round != g.engine.round_no
    g.engine.fugitive.ram = int(g.engine.config["blackout_cost"]) + int(g.engine.config["ping_cost"])
    trace0 = g.engine.fugitive.trace
    r = client.post("/api/train/fugitive/ping", headers=auth(tok["adm"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pinged"] is True and body["ram"] == int(g.engine.config["blackout_cost"])
    assert body["trace"] == trace0 + int(g.engine.config["ping_trace"]) and set(body["orders"]) == {"h1", "h2"}
    st = recv(adm, "state", skip=("fugitive_submitted",))["state"]
    assert st["fugitive"]["pinged"] is True and st["fugitive"]["ram"] == body["ram"] and st["fugitive"]["trace"] == body["trace"]


def test_votes_need_counts_only_humans_awake(client):
    """F22: AI hunters never vote and dazed hunters are not counted; the need never drops below 1."""
    from app.train import engine as E
    tok = setup(client, hunters=("h1", "h2", "h3", "h4"))
    g = mgr(client).game
    assert g.votes_needed("h4") == 2 and g.votes_needed() == 2
    g.engine.hunters["h3"].dazed_until = g.engine.round_no
    assert g.votes_needed("h4") == 2      # h1, h2 → 2//2+1
    g.engine.hunters["h2"].dazed_until = g.engine.round_no
    assert g.votes_needed("h4") == 1
    # two humans + two bots: one awake human against the other is enough
    for uid in ("bot:1", "bot:2"):
        g.engine.hunters[uid] = E.Hunter(user_id=uid, name=uid, room="A1")
    del g.engine.hunters["h3"], g.engine.hunters["h4"]
    g.engine.hunters["h2"].dazed_until = -1
    assert g.votes_needed("h2") == 1 and g.votes_needed("bot:1") == 2
    s = state(client, tok["h1"])
    assert s["vote_need"] == {"h1": 1, "h2": 1, "bot:1": 2, "bot:2": 2}
    assert s["labels"]["bot:1"] == "제미나이-1" and s["labels"]["h1"] == "h1"


def test_escape_on_freeze_ends_the_chase(client, stack):
    """F05: the safety freeze without a capture is the fugitive's win (status ESCAPED)."""
    tok = setup(client, overrides={"overheat_rounds": 0})
    m = mgr(client)
    lines = []

    async def fake_hook(line):
        lines.append(line)

    m.webhook = fake_hook
    g = m.game
    g.engine.fugitive.trace = 100   # traced this round; overheat 0 → frozen at once
    g.engine.bot_reasons.append({"round": 1, "uid": "fugitive", "name": "x", "order": "stay", "target": None,
                                 "reason": "Gemini 호출 실패로 대기: Traceback secret", "accepted": True, "note": "",
                                 "error": "api_error"})
    h2 = stack.enter_context(ws_auth(client, tok["h2"]))
    recv(h2, "hello")
    for h in ("h1", "h2"):
        client.post("/api/train/order", json={"type": "stay"}, headers=auth(tok[h]))
    client.post("/api/train/fugitive/order", json={}, headers=auth(tok["adm"]))
    rr = recv(h2, "round_resolved")
    assert rr["report"]["frozen"] is True and rr["report"]["captured_by"] is None and rr["state"]["status"] == "ESCAPED"
    assert_hunter_safe(rr)
    esc = recv(h2, "escaped")
    assert esc["round"] == 1 and "빠져나갔어요" in esc["line"]
    wait_for(lambda: lines == [esc["line"]])
    wait_for(lambda: g.policy.webhook_sent is True)
    assert g.status == "ESCAPED" and m._timer is None and g.policy.grace_until is None
    s = state(client, tok["h1"])
    assert s["status"] == "ESCAPED" and s["view"]["capture_room"] is None and "ai_log" not in s
    assert_hunter_safe(s)
    assert client.post("/api/train/order", json={"type": "stay"}, headers=auth(tok["h1"])).status_code == 409
    assert client.put("/api/train/config", json={"set": {"scan_budget": 1}}, headers=auth(tok["adm"])).status_code == 409
    # the route and the AI log open together after the chase, the log without raw error text (F64)
    assert client.post("/api/train/reveal", json={"on": True}, headers=auth(tok["adm"])).status_code == 200
    s = state(client, tok["h1"])
    assert [x["round"] for x in s["route"]] == [1]
    assert s["ai_log"][0]["reason"] == "AI 응답을 받지 못해 이번 라운드는 대기했어요" and "Traceback" not in json.dumps(s)
    # anyone may open the next chase (F56 kept), and the snapshot keeps ESCAPED
    from app.train import store
    assert store.load_active_game()[1] == "ESCAPED"
    r = client.post("/api/train/game", json={"hunter_count": 2}, headers=auth(tok["h1"]))
    assert r.json()["status"] == "LOBBY" and mgr(client).admin_id == "h1"


def test_escape_restored_and_webhook_resent(env):
    from fastapi.testclient import TestClient
    from app.main import create_app

    with TestClient(create_app()) as c:
        tok = setup(c, overrides={"max_rounds": 1})
        m = mgr(c)

        async def broken(_line):
            return False

        m.webhook = broken
        for h in ("h1", "h2"):
            c.post("/api/train/order", json={"type": "stay"}, headers=auth(tok[h]))
        c.post("/api/train/fugitive/order", json={}, headers=auth(tok["adm"]))
        assert m.game.status == "ESCAPED" and m.game.policy.webhook_sent is False
    sent = []

    async def hook(line):
        sent.append(line)
        return True

    from app.train import game as G
    orig = G.post_webhook
    G.post_webhook = hook
    try:
        with TestClient(create_app()) as c:
            m = mgr(c)
            assert m.game.status == "ESCAPED"
            wait_for(lambda: sent == [G.ESCAPE_LINE])
            wait_for(lambda: m.game.policy.webhook_sent is True)
            assert state(c, tok["h1"])["status"] == "ESCAPED"
    finally:
        G.post_webhook = orig


def test_start_scales_by_boarding_count(client, monkeypatch, env):
    """F09: a 6-seat lobby that leaves with 2 hunters plays the 2-hunter map and balance; an admin-picked map stays."""
    from app import config
    from app.train import settings
    path = env["data"] / "train_config.json"
    path.write_text(json.dumps({"_comment": "x", "scan_budget": 1, "2": {"trace_passive": 3}, "6": {"trace_passive": 9}}),
                    encoding="utf-8")
    monkeypatch.setattr(config, "TRAIN_CONFIG_PATH", path)
    adm, h1, h2 = (register(client, x) for x in ("adm", "h1", "h2"))
    r = client.post("/api/train/game", json={"hunter_count": 6}, headers=auth(adm)).json()
    assert r["scaled_for"] == 2 and r["map_id"] == "car2077_9"   # an empty lobby would scale for 2
    client.post("/api/train/join", headers=auth(h1))
    client.post("/api/train/join", headers=auth(h2))
    st = client.post("/api/train/start", headers=auth(adm)).json()
    g = mgr(client).game
    assert st["scaled_for"] == 2 and st["map_id"] == "car2077_9" and g.engine.map_id == "car2077_9"
    assert g.engine.config["trace_passive"] == 3 and g.engine.config["scan_budget"] == 1   # per-seat section after flat keys
    assert g.engine.config["ping_signature"] is True and g.engine.config["escape_on_freeze"] is True
    assert settings.build(6)[0]["trace_passive"] == 9
    # the randomised placement went into the engine config, and stays out of hunter payloads
    assert g.engine.config["fugitive_start"] == g.engine.position_history[0]
    assert "fugitive_start" not in json.dumps(state(client, h1))
    client.post("/api/train/game/end", headers=auth(adm))
    # an explicitly chosen map is kept
    client.post("/api/train/game", json={"hunter_count": 6}, headers=auth(adm))
    assert client.put("/api/train/config", json={"map_id": "car2077_12"}, headers=auth(adm)).json()["map_chosen"] is True
    client.post("/api/train/join", headers=auth(h1))
    client.post("/api/train/join", headers=auth(h2))
    assert client.post("/api/train/start", headers=auth(adm)).json()["map_id"] == "car2077_12"


def test_placement_is_random_and_central():
    """F12: the start room varies among the near-central rooms; spawns are the farthest rooms, shuffled."""
    import random
    from app.train import engine as E, settings
    gmap = E.GameMap.builtin("car2077_12")
    ecc = {r: max(gmap.distance(r, o) for o in gmap.rooms) for r in gmap.rooms}
    starts, firsts = set(), set()
    for seed in range(40):
        start, spawns = settings.placement(gmap, 4, {"fugitive_start": "auto", "hunter_spawn_rooms": "auto"},
                                           random.Random(seed))
        pool = spawns.split(",")
        assert ecc[start] <= min(ecc.values()) + 1 and len(pool) == 4 and start not in pool
        starts.add(start)
        firsts.add(pool[0])
    assert len(starts) > 2 and len(firsts) > 2
    assert settings.placement(gmap, 4, {"fugitive_start": "C4", "hunter_spawn_rooms": "A1"}, random.Random(1)) == ("C4", "A1")


def test_lobby_member_may_end_lobby(client):
    """F10: a lobby whose opener vanished can be closed by anyone waiting in it; a running game stays admin-only."""
    adm, h1, h2, spec = (register(client, x) for x in ("adm", "h1", "h2", "spec"))
    client.post("/api/train/game", json={"hunter_count": 2}, headers=auth(adm))
    client.post("/api/train/join", headers=auth(h1))
    assert client.post("/api/train/game/end", headers=auth(spec)).json()["error"] == "not_admin"
    assert client.post("/api/train/game/end", headers=auth(h1)).json() == {"status": "IDLE"}


def test_running_game_end_stays_admin_only(client):
    tok = setup(client)
    assert client.post("/api/train/game/end", headers=auth(tok["h1"])).json()["error"] == "not_admin"
    assert client.post("/api/train/game/end", headers=auth(tok["adm"])).json() == {"status": "IDLE"}


def test_override_keys_public_without_values(client):
    """F32: hunters see which tunables the admin overrode, never the values of private ones."""
    tok = setup(client)
    client.put("/api/train/config", json={"set": {"trace_passive": 3, "scan_budget": 1}}, headers=auth(tok["adm"]))
    s = state(client, tok["h1"])
    assert s["override_keys"] == ["scan_budget", "trace_passive"]
    assert "trace_passive" not in s["config"]
    assert_hunter_safe(s)


class GatedGemini(FakeGemini):
    """generate_content blocks until `gate` is set (the AI decides last / times out)."""

    def __init__(self, text: str):
        import threading
        super().__init__(text)
        self.gate = threading.Event()

    def generate_content(self, model, contents, config=None):
        self.gate.wait(5)
        return super().generate_content(model, contents, config)


def test_ai_last_submitter_resolves_and_everyone_sees_it(client, stack):
    """F02: the AI's submit resolves the round inside its own task; the next round's scheduling must not cancel that
    task before round_resolved/round_open went out. F52: hunters get bot_thinking."""
    from app.train import bot_player as B
    adm, h1 = register(client, "adm"), register(client, "h1")
    client.post("/api/train/game", json={"hunter_count": 3}, headers=auth(adm))
    fake = GatedGemini('{"order": "stay", "reason": "봇 대기"}')
    mgr(client).bot_player = B.GeminiPlayer(client=fake)
    client.post("/api/train/join", headers=auth(h1))
    client.post("/api/train/bots", json={"target_count": 3}, headers=auth(adm))
    ws = stack.enter_context(ws_auth(client, h1))
    recv(ws, "hello")
    client.post("/api/train/start", headers=auth(adm))
    assert recv(ws, "bot_thinking", skip=("state", "started", "round_open"))["id"] == "bot:1"
    client.post("/api/train/order", json={"type": "stay"}, headers=auth(h1))
    client.post("/api/train/fugitive/order", json={}, headers=auth(adm))
    eng = mgr(client).game.engine
    assert eng.round_no == 1
    fake.gate.set()   # both bots answer; the second one completes the crew → resolve inside the bot task
    rr = recv(ws, "round_resolved")
    assert rr["report"]["round"] == 1
    assert recv(ws, "round_open")["round"] == 2
    wait_for(lambda: all(h.order is not None for uid, h in eng.hunters.items() if uid.startswith("bot:")))
    assert eng.round_no == 2


def test_ai_timeout_waits(client, monkeypatch):
    """F39: a Gemini call that hangs makes the bot wait this round instead of stalling every later bot."""
    from app.train import bot_player as B, game as G
    monkeypatch.setattr(G, "AI_TIMEOUT_S", 0.2)
    adm, h1 = register(client, "adm"), register(client, "h1")
    client.post("/api/train/game", json={"hunter_count": 3}, headers=auth(adm))
    fake = GatedGemini('{"order": "search", "reason": "늦은 답"}')
    mgr(client).bot_player = B.GeminiPlayer(client=fake)
    client.post("/api/train/join", headers=auth(h1))
    client.post("/api/train/bots", json={"target_count": 3}, headers=auth(adm))
    client.post("/api/train/start", headers=auth(adm))
    eng = mgr(client).game.engine
    try:
        wait_for(lambda: len(eng.bot_reasons) == 2, timeout=3.0)
    finally:
        fake.gate.set()
    for r in eng.bot_reasons:
        assert r["order"] == "stay" and r["error"] == "timeout" and r["note"] == "시간 초과 → 대기"
    assert all(eng.hunters[u].order.type == "stay" for u in ("bot:1", "bot:2"))


def test_bot_capture_line_uses_label():
    """F15: engine names stay uids; texts the server builds read "제미나이-N" for AI hunters."""
    from app.train import game as G, views
    from types import SimpleNamespace
    assert views.label_of("bot:2") == "제미나이-2" and views.label_of("h1") == "h1"
    line = G.Manager._capture_line(SimpleNamespace(captured_by="bot:2"))
    assert line.startswith("**수수께끼의 인영을 제미나이-2가 잡았다!**")


def test_map_room_ids_must_be_uppercase():
    """F51: the AI fugitive's parser upper-cases room ids, so a lowercase map would never let it move."""
    from app.train import maps
    rows = [{"room": "a1", "device": "curtain", "neighbors": "a2", "col": 1, "row": 1},
            {"room": "a2", "device": "light", "neighbors": "a1", "col": 2, "row": 1}]
    assert "대문자" in maps.validate("lower", rows)
    up = [{**r, "room": r["room"].upper(), "neighbors": r["neighbors"].upper()} for r in rows]
    assert maps.validate("upper", up) is None
