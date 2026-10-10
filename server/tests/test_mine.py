"""The mine: ore nodes spawned once per KST day on free floor cells; walk next to one and press 채광 until it breaks."""
import importlib
import json
import sys

import pytest

from conftest import auth, recv, register

MINE_ROOM = {
    "id": "mine", "name": "광산", "kind": "mine", "cols": 7, "rows": 6, "wall_rows": 1, "spawn": {"x": 3, "y": 3},
    "blocked": [[6, 5]], "zoom": 2, "tiles": {"wall": ["tile_wall"], "floor": "tile_floor"},
    "floor": [[None] * 7 for _ in range(4)] + [[None, None, None, None, None, "tile_water", None], [None] * 7],
    "exits": [{"x": 0, "y": 5, "w": 1, "h": 1, "to": "map", "spawn": {"x": 0, "y": 0}}],
    "seed": [{"item_id": "stairs", "x": 1, "y": 1}],
}
TAKEN = {(6, 5), (3, 3), (5, 4), (0, 5), (1, 1)}  # blocked, spawn, water, exit, seeded stairs
SKIP = ("event", "progress", "join", "leave", "move", "money", "mine")  # frames a mining session also hears
MINE_CFG = {
    "room": "mine", "per_day": 3, "hit_cooldown_ms": 0, "reach": 1,
    "pickaxe": {"file": "Map/Mine/x.png", "x": 0, "y": 32},
    "ores": [{"id": "copper", "name": "구리 광석", "hits": 1, "value": 8, "weight": 1, "icon": {"file": "Map/Mine/x.png", "x": 0, "y": 0}},
             {"id": "gold", "name": "금 광석", "hits": 3, "value": 45, "weight": 1}],
}


@pytest.fixture()
def mine_env(env):
    (env["rooms"] / "mine.json").write_text(json.dumps(MINE_ROOM, ensure_ascii=False), encoding="utf-8")
    (env["data"] / "mine.json").write_text(json.dumps(MINE_CFG, ensure_ascii=False), encoding="utf-8")
    importlib.reload(sys.modules["app.catalog"])
    return env


@pytest.fixture()
def mclient(mine_env):
    from fastapi.testclient import TestClient
    from app.main import create_app
    with TestClient(create_app()) as c:
        yield c


def _db():
    from app import config, db
    return db.connect(config.DB_PATH)


def _set_kinds(kinds: list[str]) -> list[int]:
    """Force the spawned kinds (the spawn draws them at random) and return the node seqs in order."""
    conn = _db()
    seqs = [r[0] for r in conn.execute("SELECT seq FROM ore_nodes WHERE mined_by IS NULL ORDER BY seq").fetchall()]
    for seq, k in zip(seqs, kinds):
        hits = next(o["hits"] for o in MINE_CFG["ores"] if o["id"] == k)
        conn.execute("UPDATE ore_nodes SET kind = ?, hits_left = ? WHERE seq = ?", (k, hits, seq))
    conn.close()
    return seqs


def _stand_next_to(ws, node):
    """Enter the mine standing one cell right of the node (or left when it is on the last column)."""
    x = node["x"] + 1 if node["x"] + 1 < MINE_ROOM["cols"] else node["x"] - 1
    ws.send_text(json.dumps({"type": "enter", "room": "mine", "x": x + 0.5, "y": node["y"] + 1}))
    recv(ws, "entered", skip=SKIP)


def test_no_mine_without_config(client):
    assert client.get("/api/mine").status_code == 404
    assert client.get("/api/mine").json()["error"] == "no_mine"


def test_spawn_once_a_day_on_free_floor_cells(mclient):
    from app import mine
    info = mclient.get("/api/mine").json()
    assert info == {"room": "mine", "per_day": 3, "hit_cooldown_ms": 0, "reach": 1,
                    "ores": [{"id": "copper", "name": "구리 광석", "hits": 1, "value": 8}, {"id": "gold", "name": "금 광석", "hits": 3, "value": 45}]}
    assert "icon" not in json.dumps(info) and "file" not in json.dumps(info)
    r = mclient.get("/api/mine/nodes").json()
    assert r["left"] == 3 and r["per_day"] == 3 and len(r["nodes"]) == 3
    cells = {(n["x"], n["y"]) for n in r["nodes"]}
    assert len(cells) == 3 and not (cells & TAKEN) and all(1 <= y < 6 and 0 <= x < 7 for x, y in cells)
    assert all(n["hits_left"] == n["hits"] >= 1 for n in r["nodes"])
    assert r["resets_at"] > 0 and mine.day_key(r["resets_at"]) == r["day"] + 1 and mine.day_key(r["resets_at"] - 1) == r["day"]
    # the same day again: nothing more
    conn = _db()
    from app.db import transaction
    cfg = mclient.app.state.mine.cfg
    cat = mclient.app.state.catalog
    with transaction(conn):
        assert mine.spawn_day(conn, cat, cfg) == 0
        # tomorrow: a fresh set, yesterday's leftovers no longer count
        tomorrow = r["resets_at"] + 60
        assert mine.spawn_day(conn, cat, cfg, tomorrow) == 3
        nxt = mine.nodes(conn, cfg, tomorrow)
        assert nxt["day"] == r["day"] + 1 and nxt["left"] == 3 and {n["seq"] for n in nxt["nodes"]}.isdisjoint({n["seq"] for n in r["nodes"]})
        assert mine.spawn_day(conn, cat, cfg, tomorrow) == 0
    conn.close()


def test_hits_need_the_avatar_next_to_the_node_and_the_last_hit_pays(mclient):
    lun = register(mclient, "lun")
    kim = register(mclient, "kim")
    copper, gold, _ = _set_kinds(["copper", "gold", "copper"])
    nodes = {n["seq"]: n for n in mclient.get("/api/mine/nodes").json()["nodes"]}
    # not online at all / not in the mine / too far away
    assert mclient.post("/api/mine/hit", json={"seq": copper}, headers=auth(lun)).json()["error"] == "not_here"
    with mclient.websocket_connect("/ws") as ws, mclient.websocket_connect("/ws") as ws2:
        ws.send_text(json.dumps({"type": "auth", "token": lun}))
        recv(ws, "hello")
        ws2.send_text(json.dumps({"type": "auth", "token": kim}))
        recv(ws2, "hello")
        assert mclient.post("/api/mine/hit", json={"seq": copper}, headers=auth(lun)).json()["error"] == "not_here"
        far = {"x": 6 if nodes[copper]["x"] < 3 else 0, "y": 5 if nodes[copper]["y"] < 3 else 1}
        ws.send_text(json.dumps({"type": "enter", "room": "mine", "x": far["x"] + 0.5, "y": far["y"] + 1}))
        recv(ws, "entered", skip=SKIP)
        assert mclient.post("/api/mine/hit", json={"seq": copper}, headers=auth(lun)).json()["error"] == "not_here"
        # kim watches from inside the mine (the `mine` message only goes to that room)
        ws2.send_text(json.dumps({"type": "enter", "room": "mine", "x": 3.5, "y": 2}))
        recv(ws2, "entered", skip=SKIP)

        _stand_next_to(ws, nodes[copper])
        r = mclient.post("/api/mine/hit", json={"seq": copper}, headers=auth(lun)).json()
        assert r["done"] is True and r["hits_left"] == 0 and r["id"] == "copper" and r["value"] == 8 and r["left"] == 2
        assert r["ledger_seq"] is not None and r["deliverable"] == [] and r["balance"] == 800 + 8
        m = recv(ws2, "mine", skip=SKIP)
        assert m == {"type": "mine", "seq": copper, "x": nodes[copper]["x"], "y": nodes[copper]["y"], "kind": "copper",
                     "hits_left": 0, "by": "lun", "done": True, "left": 2, "loot": {"id": "copper", "name": "구리 광석", "value": 8}}
        # a broken node is gone
        assert mclient.post("/api/mine/hit", json={"seq": copper}, headers=auth(lun)).json()["error"] == "node_gone"
        assert mclient.post("/api/mine/hit", json={"seq": 9999}, headers=auth(lun)).json()["error"] == "node_gone"

        # gold takes three presses; nothing is paid before the last one
        _stand_next_to(ws, nodes[gold])
        r = mclient.post("/api/mine/hit", json={"seq": gold}, headers=auth(lun)).json()
        assert r == {"seq": gold, "hits_left": 2, "done": False, "left": 2, "balance": 808}
        m = recv(ws2, "mine", skip=SKIP)
        assert m["hits_left"] == 2 and m["done"] is False and "loot" not in m
        assert mclient.post("/api/mine/hit", json={"seq": gold}, headers=auth(lun)).json()["hits_left"] == 1
        r = mclient.post("/api/mine/hit", json={"seq": gold}, headers=auth(lun)).json()
        assert r["done"] is True and r["value"] == 45 and r["balance"] == 853 and r["left"] == 1

    act = mclient.get("/api/activity", headers=auth(lun)).json()
    ev = [e for e in act["events"] if e["kind"] == "mine"]
    assert [(e["item_id"], e["amount"], e["player_id"], e["room_id"]) for e in ev] == [("gold", 45, "lun", "mine"), ("copper", 8, "lun", "mine")]
    assert act["today"]["mine"] == 53 and act["today"]["mine_count"] == 2
    assert "mine" not in act["comfort"]  # the mine takes no guests
    conn = _db()
    rows = conn.execute("SELECT kind, item_id, amount, player_id FROM ledger WHERE kind = 'mine' ORDER BY seq").fetchall()
    assert [tuple(r) for r in rows] == [("mine", "mine:copper", -8, "lun"), ("mine", "mine:gold", -45, "lun")]
    assert conn.execute("SELECT COUNT(*) FROM ore_nodes WHERE mined_by = 'lun'").fetchone()[0] == 2
    conn.close()


def test_hit_cooldown(mclient):
    lun = register(mclient, "lun")
    mclient.app.state.mine.cfg.hit_cooldown_ms = 1000
    gold, _, _ = _set_kinds(["gold", "gold", "gold"])
    node = next(n for n in mclient.get("/api/mine/nodes").json()["nodes"] if n["seq"] == gold)
    with mclient.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": lun}))
        recv(ws, "hello")
        _stand_next_to(ws, node)
        assert mclient.post("/api/mine/hit", json={"seq": gold}, headers=auth(lun)).json()["hits_left"] == 2
        r = mclient.post("/api/mine/hit", json={"seq": gold}, headers=auth(lun))
        assert r.status_code == 429 and r.json()["error"] == "mine_cooldown"


def test_ore_can_be_delivered_to_a_stage_that_wants_it(mine_env):
    p = mine_env["rooms"] / "house_a.json"
    room = json.loads(p.read_text(encoding="utf-8"))
    room["restore"] = [{"id": "ore", "name": "광석", "need": [{"type": "deliver", "kind": "mine", "count": 1, "id": "copper"}],
                        "reward": [{"type": "unlock", "room": "dock"}]}]
    p.write_text(json.dumps(room, ensure_ascii=False), encoding="utf-8")
    importlib.reload(sys.modules["app.catalog"])
    from fastapi.testclient import TestClient
    from app.main import create_app
    with TestClient(create_app()) as client:
        lun = register(client, "lun")
        copper, gold, _ = _set_kinds(["copper", "gold", "copper"])
        nodes = {n["seq"]: n for n in client.get("/api/mine/nodes").json()["nodes"]}
        with client.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({"type": "auth", "token": lun}))
            recv(ws, "hello")
            # gold is not what the stage wants
            _stand_next_to(ws, nodes[gold])
            for _ in range(2):
                client.post("/api/mine/hit", json={"seq": gold}, headers=auth(lun))
            r = client.post("/api/mine/hit", json={"seq": gold}, headers=auth(lun)).json()
            assert r["done"] and r["deliverable"] == []
            assert client.post("/api/deliver", json={"seq": r["ledger_seq"]}, headers=auth(lun)).json()["error"] == "nothing_to_deliver"
            _stand_next_to(ws, nodes[copper])
            r = client.post("/api/mine/hit", json={"seq": copper}, headers=auth(lun)).json()
            assert r["deliverable"] == [{"room": "house_a", "name": "빈 집", "have": 0, "want": 1}]
            d = client.post("/api/deliver", json={"seq": r["ledger_seq"]}, headers=auth(lun)).json()
            assert d == {"balance": 845, "room": "house_a", "have": 1, "want": 1, "completed": [{"room": "house_a", "stage": "ore", "name": "광석"}]}
        act = client.get("/api/activity", headers=auth(lun)).json()
        ev = next(e for e in act["events"] if e["kind"] == "deliver")
        assert ev["item_id"] == "copper" and ev["amount"] == -8 and ev["data"] == {"stage": 0, "kind": "mine"}
        assert client.get("/api/rooms").json()["locked"] == []
        # a fish-only need never counts ore (and the other way round) — the per-kind dict keeps them apart
        from app.progress import deliveries_by_room
        conn = _db()
        assert deliveries_by_room(conn, "house_a", 0) == {"fish": {"*": 0}, "mine": {"copper": 1, "*": 1}}
        conn.close()


def test_no_furniture_in_the_mine(mclient):
    lun = register(mclient, "lun")
    r = mclient.post("/api/room/place", json={"room_id": "mine", "item_id": "chair", "x": 2, "y": 2}, headers=auth(lun))
    assert r.status_code == 403 and r.json()["error"] == "no_place"
    rooms = {r["id"]: r for r in mclient.get("/api/rooms").json()["rooms"]}
    assert rooms["mine"]["kind"] == "mine" and rooms["mine"]["comfort"] is None and rooms["inn"]["kind"] == "room"
    assert next(r for r in mclient.get("/api/catalog").json()["rooms"] if r["id"] == "mine")["kind"] == "mine"


def test_mine_json_must_name_a_mine_room(mine_env):
    cfg = json.loads((mine_env["data"] / "mine.json").read_text(encoding="utf-8"))
    cfg["room"] = "inn"
    (mine_env["data"] / "mine.json").write_text(json.dumps(cfg), encoding="utf-8")
    from fastapi.testclient import TestClient
    from app.main import create_app
    with pytest.raises(ValueError, match="mine.json"):
        with TestClient(create_app()):
            pass
