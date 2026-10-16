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


def recv(ws, kind, skip=("state", "submitted", "vote", "deadline", "round_open", "hunter_order", "fugitive_submitted")):
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
        tok = setup(c, overrides={"round_timer_sec": 50})
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
    # 2 hunters → 1 vote passes, the target is submitted as "stay" and (fugitive frozen? no) grace starts
    r = client.post("/api/train/vote", json={"target": "h2"}, headers=auth(tok["h1"]))
    assert r.json() == {"votes": ["h1"], "need": 1, "passed": True}
    assert g.engine.hunters["h2"].order.type == "stay"
    assert client.post("/api/train/vote", json={"target": "h2"}, headers=auth(tok["h1"])).json()["error"] == "vote_bad_target"


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
