"""The mine: floors generated once per KST day (rocks, ore nodes, a hidden ladder); walk next to a node and press 채광."""
import importlib
import json
import random
import sys

import pytest

from conftest import auth, recv, register

MINE_ROOM = {
    "id": "mine", "name": "광산", "kind": "mine", "cols": 9, "rows": 8, "wall_rows": 2, "spawn": {"x": 4, "y": 3},
    "blocked": [[8, 7]], "zoom": 2, "tiles": {"wall": ["tile_wall", "tile_wall"], "floor": "tile_floor"},
    "floor": [[None] * 9 for _ in range(6)] + [[None, None, None, None, None, "tile_water", None, None, None], [None] * 9],
    "exits": [{"x": 0, "y": 7, "w": 1, "h": 1, "to": "map", "spawn": {"x": 0, "y": 0}}],
    "seed": [{"item_id": "stairs", "x": 1, "y": 2}],
}
TAKEN = {(8, 7), (4, 3), (5, 6), (0, 7), (1, 2)}  # blocked, spawn, water, exit, seeded stairs
SKIP = ("event", "progress", "join", "leave", "move", "money", "mine")  # frames a mining session also hears
MINE_CFG = {
    "room": "mine", "floors": 3, "nodes_per_floor": 4, "hit_cooldown_ms": 0, "reach": 1, "rock_density": 0.15,
    "rocks": ["rock_a", "rock_b"], "ladder": "hole", "ladder_chance": 0.0,
    "pickaxe": ["pick_1", "pick_2"],
    "ores": [{"id": "stone", "name": "돌", "hits": 1, "value": 0, "sprite": "mine_stone"},
             {"id": "copper", "name": "구리 광석", "hits": 1, "value": 8, "sprite": "mine_copper"},
             {"id": "gold", "name": "금 광석", "hits": 3, "value": 45, "sprite": "mine_wall_gold", "wall": True}],
    "tiers": [{"floors": [1, 2], "weights": {"stone": 1, "copper": 1, "gold": 1}},
              {"floors": [3, 3], "weights": {"stone": 1, "gold": 3}}],
}


@pytest.fixture()
def mine_env(env):
    (env["rooms"] / "mine.json").write_text(json.dumps(MINE_ROOM, ensure_ascii=False), encoding="utf-8")
    (env["data"] / "mine.json").write_text(json.dumps(MINE_CFG, ensure_ascii=False), encoding="utf-8")
    import app.catalog
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


def _set_kinds(kinds: list[str], floor: int = 1) -> list[int]:
    """Force the standing floor nodes' kinds (the generator draws them at random) and return their seqs in order.
    Wall ores stay where they are (the cell row matters only for reach, which _stand_next_to handles)."""
    conn = _db()
    seqs = [r[0] for r in conn.execute("SELECT seq FROM ore_nodes WHERE floor = ? AND mined_by IS NULL ORDER BY seq", (floor,)).fetchall()]
    for seq, k in zip(seqs, kinds):
        hits = next(o["hits"] for o in MINE_CFG["ores"] if o["id"] == k)
        conn.execute("UPDATE ore_nodes SET kind = ?, hits_left = ?, ladder = 0 WHERE seq = ?", (k, hits, seq))
    conn.close()
    return seqs


def _enter(ws, floor: int, x: float, y: float):
    ws.send_text(json.dumps({"type": "enter", "room": f"mine#{floor}", "x": x, "y": y}))
    return recv(ws, ("entered", "error"), skip=SKIP)


def _stand_next_to(ws, node, floor: int = 1):
    """Enter the floor standing right of the node (left when it is on the last column); a wall ore is mined from below."""
    y = node["y"] + 1 if node["y"] < MINE_ROOM["wall_rows"] else node["y"]
    x = node["x"] + 1 if node["x"] + 1 < MINE_ROOM["cols"] else node["x"] - 1
    m = _enter(ws, floor, x + 0.5, y + 1)
    assert m["type"] == "entered", m


def test_no_mine_without_config(client):
    assert client.get("/api/mine").status_code == 404
    assert client.get("/api/mine").json()["error"] == "no_mine"
    assert client.get("/api/mine/floor/1").json()["error"] == "no_mine"


def test_config_validation(mine_env):
    from app import mine
    from pathlib import Path
    p = mine_env["data"] / "mine.json"
    orig = p.read_text(encoding="utf-8")

    def bad(patch, match):
        cfg = json.loads(orig)
        patch(cfg)
        p.write_text(json.dumps(cfg), encoding="utf-8")
        with pytest.raises(ValueError, match=match):
            mine.load_config(Path(p))

    bad(lambda c: c["tiers"].pop(0), "without gaps")
    bad(lambda c: c.__setitem__("floors", 4), "floors is 4")
    bad(lambda c: c["tiers"][0]["weights"].__setitem__("mithril", 1), "unknown ore")
    bad(lambda c: c["tiers"][1]["weights"].pop("stone"), "value-0")
    bad(lambda c: c["ores"].append(dict(c["ores"][0])), "duplicate")
    assert mine.load_config(Path("/nope/mine.json")) is None


def test_floor_layout_rocks_nodes_and_ladder(mclient):
    from app import mine
    info = mclient.get("/api/mine").json()
    assert info["floors"] == 3 and info["nodes_per_floor"] == 4 and info["ladder"] == "hole" and info["deepest"] == 1
    assert [o["id"] for o in info["ores"]] == ["stone", "copper", "gold"] and info["ores"][2]["wall"] is True
    assert info["ores"][0]["sprite"] == "mine_stone" and "rocks" not in info and "file" not in json.dumps(info)
    r = mclient.get("/api/mine/floor/1").json()
    assert r["floor"] == 1 and r["floors"] == 3 and r["deepest"] == 1 and r["ladder"] is None and r["per_floor"] == 4
    assert r["left"] == len(r["nodes"]) and 4 <= len(r["nodes"]) <= 5  # +1 when no dud was drawn (the ladder needs one)
    rocks = {(x, y): k for x, y, k in r["rocks"]}
    assert rocks and all(k in ("rock_a", "rock_b") for k in rocks.values()) and not (set(rocks) & TAKEN)
    assert all(2 <= y < 8 for _, y in rocks)
    cells = [(n["x"], n["y"]) for n in r["nodes"]]
    assert len(set(cells)) == len(cells) and not (set(cells) & TAKEN) and not (set(cells) & set(rocks))
    for n in r["nodes"]:
        assert n["hits_left"] == n["hits"] >= 1
        if n["wall"]:
            assert n["kind"] == "gold" and n["y"] == 1 and (n["x"], 2) not in rocks  # wall ore above a reachable floor cell
        else:
            assert 2 <= n["y"] < 8
    # every free floor cell is reachable from the spawn (pockets were filled with rock)
    cat = mclient.app.state.catalog
    room = cat.rooms["mine"]
    reach = mine._reachable(cat, room, set(rocks))
    conn = _db()
    for c in mine.free_cells(conn, cat, mclient.app.state.mine.cfg, set(rocks)):
        assert c in reach, c
    # exactly one node hides the ladder on a floor that is not the last
    assert conn.execute("SELECT COUNT(*) FROM ore_nodes WHERE floor = 1 AND ladder = 1").fetchone()[0] == 1
    assert conn.execute("SELECT kind FROM ore_nodes WHERE floor = 1 AND ladder = 1").fetchone()[0] == "stone"
    # the same day again: nothing new; tomorrow: a fresh floor, yesterday's nodes no longer count
    from app.db import transaction
    cfg = mclient.app.state.mine.cfg
    with transaction(conn):
        assert mine.ensure_floor(conn, cat, cfg, 1) is False
        tomorrow = r["resets_at"] + 60
        assert mine.day_key(tomorrow) == r["day"] + 1
        assert mine.ensure_floor(conn, cat, cfg, 1, tomorrow) is True
        nxt = mine.floor_view(conn, cfg, 1, tomorrow)
        assert nxt["day"] == r["day"] + 1 and nxt["left"] >= 4 and {n["seq"] for n in nxt["nodes"]}.isdisjoint({n["seq"] for n in r["nodes"]})
        assert mine.ensure_floor(conn, cat, cfg, 1, tomorrow) is False
        # the last floor has no ladder node
        assert mine.ensure_floor(conn, cat, cfg, 3, tomorrow) is True
        assert conn.execute("SELECT COUNT(*) FROM ore_nodes WHERE floor = 3 AND ladder = 1").fetchone()[0] == 0
    conn.close()


def test_layouts_differ_and_tiers_pick_the_ores(mine_env):
    from app import mine
    from app.main import create_app
    from fastapi.testclient import TestClient
    with TestClient(create_app()) as client:
        cat = client.app.state.catalog
        cfg = client.app.state.mine.cfg
        conn = _db()
        a = mine.layout_floor(conn, cat, cfg, 1, random.Random(1))
        b = mine.layout_floor(conn, cat, cfg, 1, random.Random(2))
        assert a != b
        kinds = {o.id for _, o, _ in mine.layout_floor(conn, cat, cfg, 3, random.Random(3))[1]}
        assert kinds <= {"stone", "gold"}
        conn.close()


def test_hits_need_the_avatar_on_the_floor_next_to_the_node_and_the_last_hit_pays(mclient):
    lun = register(mclient, "lun")
    kim = register(mclient, "kim")
    seqs = _set_kinds(["copper", "gold", "copper", "stone", "stone"])
    copper, gold = seqs[0], seqs[1]
    nodes = {n["seq"]: n for n in mclient.get("/api/mine/floor/1").json()["nodes"]}
    assert nodes[gold]["kind"] == "gold" and nodes[copper]["kind"] == "copper"
    # not online at all / not in the mine / too far away
    assert mclient.post("/api/mine/hit", json={"seq": copper}, headers=auth(lun)).json()["error"] == "not_here"
    with mclient.websocket_connect("/ws") as ws, mclient.websocket_connect("/ws") as ws2:
        ws.send_text(json.dumps({"type": "auth", "token": lun}))
        recv(ws, "hello")
        ws2.send_text(json.dumps({"type": "auth", "token": kim}))
        recv(ws2, "hello")
        assert mclient.post("/api/mine/hit", json={"seq": copper}, headers=auth(lun)).json()["error"] == "not_here"
        far = {"x": 8 if nodes[copper]["x"] < 4 else 0, "y": 7 if nodes[copper]["y"] < 4 else 2}
        assert _enter(ws, 1, far["x"] + 0.5, far["y"] + 1)["room"] == "mine#1"
        assert mclient.post("/api/mine/hit", json={"seq": copper}, headers=auth(lun)).json()["error"] == "not_here"
        # kim watches from the same floor (the `mine` message only goes there); a bare "mine" enter is floor 1
        ws2.send_text(json.dumps({"type": "enter", "room": "mine", "x": 4.5, "y": 4}))
        assert recv(ws2, "entered", skip=SKIP)["room"] == "mine#1"

        _stand_next_to(ws, nodes[copper])
        r = mclient.post("/api/mine/hit", json={"seq": copper}, headers=auth(lun)).json()
        assert r["done"] is True and r["hits_left"] == 0 and r["id"] == "copper" and r["value"] == 8 and r["left"] == len(nodes) - 1
        assert r["floor"] == 1 and "ladder" not in r
        assert r["ledger_seq"] is not None and r["deliverable"] == [] and r["balance"] == 800 + 8
        m = recv(ws2, "mine", skip=SKIP)
        assert m == {"type": "mine", "seq": copper, "floor": 1, "x": nodes[copper]["x"], "y": nodes[copper]["y"], "kind": "copper",
                     "hits_left": 0, "by": "lun", "done": True, "left": len(nodes) - 1, "loot": {"id": "copper", "name": "구리 광석", "value": 8}}
        # a broken node is gone
        assert mclient.post("/api/mine/hit", json={"seq": copper}, headers=auth(lun)).json()["error"] == "node_gone"
        assert mclient.post("/api/mine/hit", json={"seq": 9999}, headers=auth(lun)).json()["error"] == "node_gone"

        # gold (a wall ore) takes three presses from the floor cell below; nothing is paid before the last one
        _stand_next_to(ws, nodes[gold])
        r = mclient.post("/api/mine/hit", json={"seq": gold}, headers=auth(lun)).json()
        assert r == {"seq": gold, "floor": 1, "hits_left": 2, "done": False, "left": len(nodes) - 1, "balance": 808}
        m = recv(ws2, "mine", skip=SKIP)
        assert m["hits_left"] == 2 and m["done"] is False and "loot" not in m
        assert mclient.post("/api/mine/hit", json={"seq": gold}, headers=auth(lun)).json()["hits_left"] == 1
        r = mclient.post("/api/mine/hit", json={"seq": gold}, headers=auth(lun)).json()
        assert r["done"] is True and r["value"] == 45 and r["balance"] == 853 and r["left"] == len(nodes) - 2

        # standing on another floor of the mine does not count
        assert _enter(ws, 2, 1.5, 4)["code"] == "floor_locked"

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


def test_ladder_opens_the_next_floor_and_stays_reachable(mclient):
    from app import mine
    lun = register(mclient, "lun")
    conn = _db()
    # make the first node the one hiding the ladder (a floor stone), the rest plain stones with chance 0
    seqs = [r[0] for r in conn.execute("SELECT seq FROM ore_nodes WHERE floor = 1 ORDER BY seq").fetchall()]
    conn.execute("UPDATE ore_nodes SET kind = 'stone', hits_left = 1, ladder = 0 WHERE floor = 1")
    conn.execute("UPDATE ore_nodes SET ladder = 1 WHERE seq = ?", (seqs[0],))
    conn.commit()
    nodes = {n["seq"]: n for n in mclient.get("/api/mine/floor/1").json()["nodes"]}
    assert mclient.get("/api/mine/floor/2").json()["error"] == "floor_locked"
    assert mclient.get("/api/mine/floor/4").json()["error"] == "floor_locked"
    with mclient.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": lun}))
        recv(ws, "hello")
        assert _enter(ws, 2, 1.5, 4)["code"] == "floor_locked"
        # a plain stone: no money, no event, no ladder
        plain = seqs[1]
        _stand_next_to(ws, nodes[plain])
        r = mclient.post("/api/mine/hit", json={"seq": plain}, headers=auth(lun)).json()
        assert r["done"] and r["value"] == 0 and r["ledger_seq"] is None and "ladder" not in r and r["balance"] == 800
        # the ladder stone
        _stand_next_to(ws, nodes[seqs[0]])
        r = mclient.post("/api/mine/hit", json={"seq": seqs[0]}, headers=auth(lun)).json()
        n = nodes[seqs[0]]
        assert r["done"] and r["ladder"] == {"x": n["x"], "y": n["y"] if not n["wall"] else n["y"] + 1}
        assert mclient.get("/api/mine/floor/1").json()["ladder"] == r["ladder"]
        # floor 2 is open now (and generated on first look); 3 is not
        f2 = mclient.get("/api/mine/floor/2").json()
        assert f2["floor"] == 2 and f2["left"] >= 4 and f2["ladder"] is None
        assert mclient.get("/api/mine/floor/3").json()["error"] == "floor_locked"
        assert _enter(ws, 2, 1.5, 4)["room"] == "mine#2"
        assert mclient.get("/api/mine").json()["deepest"] == 2
        assert _enter(ws, 3, 1.5, 4)["code"] == "floor_locked"
        # hits on floor 1 from floor 2 are refused
        seq1 = seqs[2]
        assert mclient.post("/api/mine/hit", json={"seq": seq1}, headers=auth(lun)).json()["error"] == "not_here"
    # a reached floor stays open tomorrow even though the ladder is gone with the day
    cfg = mclient.app.state.mine.cfg
    tomorrow = f2["resets_at"] + 60
    assert mine.can_enter(conn, cfg, 2, tomorrow) and not mine.can_enter(conn, cfg, 3, tomorrow)
    assert mine.ladder_open(conn, cfg, 1, tomorrow) is None
    # ladder_chance: any other dud may open it
    cfg.ladder_chance = 1.0
    from app.db import transaction
    with transaction(conn):
        mine.ensure_floor(conn, mclient.app.state.catalog, cfg, 1, tomorrow)
        dud = conn.execute("SELECT seq FROM ore_nodes WHERE floor = 1 AND day = ? AND kind = 'stone' AND ladder = 0", (mine.day_key(tomorrow),)).fetchone()
        if dud is not None:
            h = mine.hit(conn, cfg, "lun", dud[0], tomorrow)
            assert h.done and h.ladder is not None and mine.ladder_open(conn, cfg, 1, tomorrow) == h.ladder
    conn.close()


def test_hit_cooldown(mclient):
    lun = register(mclient, "lun")
    mclient.app.state.mine.cfg.hit_cooldown_ms = 1000
    gold = _set_kinds(["gold", "gold", "gold", "gold"])[0]
    node = next(n for n in mclient.get("/api/mine/floor/1").json()["nodes"] if n["seq"] == gold)
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
        copper, gold = _set_kinds(["copper", "gold", "copper", "stone", "stone"])[:2]
        nodes = {n["seq"]: n for n in client.get("/api/mine/floor/1").json()["nodes"]}
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


def test_floor_suffix_only_on_the_mine(mclient):
    lun = register(mclient, "lun")
    with mclient.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": lun}))
        recv(ws, "hello")
        ws.send_text(json.dumps({"type": "enter", "room": "inn#2", "x": 1, "y": 1}))  # ignored
        ws.send_text(json.dumps({"type": "enter", "room": "mine#0", "x": 1, "y": 1}))  # ignored
        assert _enter(ws, 1, 4.5, 4)["room"] == "mine#1"


def test_mine_json_must_name_a_mine_room(mine_env):
    cfg = json.loads((mine_env["data"] / "mine.json").read_text(encoding="utf-8"))
    cfg["room"] = "inn"
    (mine_env["data"] / "mine.json").write_text(json.dumps(cfg), encoding="utf-8")
    from fastapi.testclient import TestClient
    from app.main import create_app
    with pytest.raises(ValueError, match="mine.json"):
        with TestClient(create_app()):
            pass
