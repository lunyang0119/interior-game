"""Guests on the DB side (guests.py): the daily settlement, catch-up, reservations, the dog lover, the views."""
import random

from conftest import auth, register

from app.comfort import load_config
from app.db import connect, now, transaction

DAY = 86400


def _settle(client, ts, rng_seed=1, cfg=None, events=None):
    from app import guests
    app = client.app
    conn = connect()
    try:
        with transaction(conn):
            return guests.settle(conn, app.state.catalog, cfg or app.state.guests, ts, random.Random(rng_seed), events)
    finally:
        conn.close()


def _meta(key):
    conn = connect()
    try:
        row = conn.execute("SELECT v FROM room_meta WHERE k = ?", (key,)).fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def _sql(q, *args):
    conn = connect()
    try:
        with transaction(conn):
            return [dict(r) for r in conn.execute(q, args).fetchall()]
    finally:
        conn.close()


def _balance(client, tok):
    return client.get("/api/me", headers=auth(tok)).json()["balance"]


def _place(client, tok, item, x, y, room="inn"):
    r = client.post("/api/room/place", json={"item_id": item, "x": x, "y": y, "room_id": room}, headers=auth(tok))
    assert r.status_code == 200, r.text
    return r.json()


def test_first_boot_marks_today_and_the_views_show_no_guests_without_a_bed(client):
    from app import guests
    today = guests.day_key(now(), client.app.state.guests)
    assert _meta("guest_day:inn") == today and _meta("guest_day:house_a") == today
    assert _sql("SELECT * FROM ledger WHERE kind = 'guest'") == []
    lun = register(client, "lun")
    inn = next(r for r in client.get("/api/rooms").json()["rooms"] if r["id"] == "inn")
    assert inn["comfort"]["inn"]["beds"] == 0 and inn["comfort"]["inn"]["guests"] == 0 and inn["comfort"]["inn"]["reservation"] is None
    act = client.get("/api/activity", headers=auth(lun)).json()
    assert act["comfort"]["inn"]["score"] == 0 and act["today"]["guests"] == 0
    # settling again today changes nothing
    assert _settle(client, now()) == 0


def test_nightly_pay_once_per_day_with_capped_catch_up(client):
    lun = register(client, "lun")
    _place(client, lun, "bed", 1, 2)
    _place(client, lun, "table", 4, 2)
    before = _balance(client, lun)
    inn = next(r for r in client.get("/api/rooms").json()["rooms"] if r["id"] == "inn")
    expect = inn["comfort"]["inn"]["pay"]
    assert inn["comfort"]["inn"]["beds"] == 1 and inn["comfort"]["inn"]["guests"] == 1 and expect > 0
    cfg = load_config().model_copy(deep=True)
    cfg.reservation.chance = 0.0  # a random reservation would be missed during the catch-up and skip a night
    t0 = now()
    ev = []
    assert _settle(client, t0 + DAY, cfg=cfg, events=ev) == expect
    assert _balance(client, lun) == before + expect
    guest = [e for e in ev if e["kind"] == "guest"]
    assert len(guest) == 1 and guest[0]["room_id"] == "inn" and guest[0]["amount"] == expect
    assert guest[0]["data"]["guests"] == 1 and guest[0]["data"]["score"] == inn["comfort"]["inn"]["score"]
    assert _settle(client, t0 + DAY, cfg=cfg) == 0  # same day twice
    # five days asleep → only max_catchup_days (3) nights are paid
    assert _settle(client, t0 + 6 * DAY, cfg=cfg) == 3 * expect
    assert len(_sql("SELECT * FROM ledger WHERE kind = 'guest'")) == 4
    act = client.get("/api/activity", headers=auth(lun)).json()
    assert act["today"]["guests"] == 4 * expect


def test_reservation_fulfilled_pays_double_and_missed_keeps_guests_away(client):
    from app import guests
    lun = register(client, "lun")
    _place(client, lun, "bed", 1, 2)
    _place(client, lun, "table", 4, 2)
    cfg = load_config().model_copy(deep=True)
    cfg.reservation.chance = 0.0
    t0 = now()
    today = guests.day_key(t0, cfg)
    _sql("INSERT INTO reservations(room_id, kind, item_id, due_day, created_ts) VALUES ('inn', 'item', 'chair', ?, ?)",
         today + 1, t0)
    view = next(r for r in client.get("/api/rooms").json()["rooms"] if r["id"] == "inn")["comfort"]["inn"]
    assert view["reservation"] == {"id": 1, "kind": "item", "item_id": "chair", "due_day": today + 1, "days_left": 1,
                                   "ready": False}
    # no chair on the due day: the guest leaves, tomorrow nobody comes
    ev = []
    paid = _settle(client, t0 + DAY, cfg=cfg, events=ev)
    assert paid > 0 and [e["kind"] for e in ev] == ["missed", "guest"]
    assert _sql("SELECT status FROM reservations")[0]["status"] == "missed"
    assert _meta("no_guests_day:inn") == today + 2
    # the view "as of" that evening says nobody is coming (the API view uses the real clock, so ask directly)
    conn = connect()
    try:
        cat = client.app.state.catalog
        view = guests.room_view(conn, cat, cat.rooms["inn"], cfg, t0 + DAY)["inn"]
    finally:
        conn.close()
    assert view["skipped"] is True and view["guests"] == 0 and view["pay"] == 0 and view["reservation"] is None
    ev = []
    assert _settle(client, t0 + 2 * DAY, cfg=cfg, events=ev) == 0
    assert [e["kind"] for e in ev] == ["guest"] and ev[0]["data"]["skipped"] is True and ev[0]["amount"] is None
    # a new reservation that is honoured: one extra guest at double the rate
    _sql("INSERT INTO reservations(room_id, kind, item_id, due_day, created_ts) VALUES ('inn', 'item', 'chair', ?, ?)",
         today + 3, t0)
    _place(client, lun, "chair", 6, 3)
    view = next(r for r in client.get("/api/rooms").json()["rooms"] if r["id"] == "inn")["comfort"]["inn"]
    assert view["reservation"]["ready"] is True  # the board can tick it off
    ev = []
    paid = _settle(client, t0 + 3 * DAY, cfg=cfg, events=ev)
    g = next(e for e in ev if e["kind"] == "guest")
    assert g["data"]["guests"] == view["guests"] + 1
    assert g["data"]["reserved"] == round(view["per_guest"] * cfg.reservation.pay_mult)
    assert paid == view["pay"] + g["data"]["reserved"]
    assert _sql("SELECT status, pay FROM reservations WHERE id = 2")[0] == {"status": "paid", "pay": g["data"]["reserved"]}


def test_reservations_are_generated_from_the_room_and_only_one_at_a_time(client):
    lun = register(client, "lun")
    _place(client, lun, "bed", 1, 2)
    cfg = load_config().model_copy(deep=True)
    cfg.reservation.chance = 1.0
    t0 = now()
    ev = []
    _settle(client, t0 + DAY, cfg=cfg, events=ev)
    res = [e for e in ev if e["kind"] == "reserve"]
    assert len(res) == 1 and res[0]["room_id"] == "inn"
    rows = _sql("SELECT * FROM reservations WHERE kind = 'item'")
    assert len(rows) == 1 and rows[0]["item_id"] == res[0]["item_id"] and rows[0]["item_id"] != "bed"
    assert cfg.reservation.lead_days[0] <= res[0]["data"]["days"] <= cfg.reservation.lead_days[1]
    # the asked-for item costs at least min_price, is furniture/surface, and is not in the room
    it = client.app.state.catalog.items[rows[0]["item_id"]]
    assert it.price >= cfg.reservation.min_price and it.layer in ("furniture", "surface_item")
    # a pending reservation blocks another one; house_a has no bed so it never gets one
    ev = []
    _settle(client, t0 + 2 * DAY, cfg=cfg, events=ev)
    assert [e for e in ev if e["kind"] == "reserve"] == []


def test_dog_lover_books_the_comfiest_room_once_a_month(client):
    from app import guests
    lun = register(client, "lun")
    _place(client, lun, "bed", 1, 2)
    cfg = load_config().model_copy(deep=True)
    cfg.reservation.chance = 0.0
    cfg.dog.comfort_fallback = 5  # a modest room is enough for the test
    t0 = now()
    # the boot settlement already decided this month; pretend it did not so the booking happens on the next pass
    _sql("DELETE FROM room_meta WHERE k = 'dog_month'")
    ev = []
    _settle(client, t0 + DAY, cfg=cfg, events=ev)
    dog = [e for e in ev if e["kind"] == "reserve" and e["data"].get("dog")]
    row = _sql("SELECT * FROM reservations WHERE kind = 'dog'")
    if not dog:  # this month's date is already past: no booking, and nothing breaks
        assert row == [] and _meta("dog_month") > 0
        return
    assert len(row) == 1 and row[0]["room_id"] == "inn" and row[0]["zone_id"] is None
    due = row[0]["due_day"]
    view = next(r for r in client.get("/api/rooms").json()["rooms"] if r["id"] == "inn")["comfort"]["inn"]
    days = due - guests.day_key(t0 + DAY, cfg)
    ev = []
    paid = _settle(client, t0 + (1 + days) * DAY, cfg=cfg, events=ev)
    g = [e for e in ev if e["kind"] == "guest" and e["data"].get("dog")]
    assert len(g) == 1 and g[0]["data"]["dog"] == round(view["per_guest"] * cfg.dog.pay_mult)
    assert paid >= g[0]["data"]["dog"]
    assert _sql("SELECT status FROM reservations WHERE kind = 'dog'")[0]["status"] == "paid"


def test_guests_leave_a_note_on_a_table(client):
    """A paid night leaves a `note` surface item owned by $guest on a surface in the unit; it scores and refunds nothing."""
    from app import guests
    lun = register(client, "lun")
    _place(client, lun, "bed", 1, 2)
    _place(client, lun, "table", 4, 2)
    cfg = load_config().model_copy(deep=True)
    cfg.reservation.chance = 0.0
    t0 = now()
    changed = set()
    conn = connect()
    try:
        with transaction(conn):
            paid = guests.settle(conn, client.app.state.catalog, cfg, t0 + DAY, random.Random(3), [], changed)
    finally:
        conn.close()
    assert paid > 0 and changed == {"inn"}
    notes = [i for i in client.get("/api/room/inn").json()["items"] if i["placed_by"] == "$guest"]
    assert len(notes) == 1 and notes[0]["item_id"] == "scrap" and notes[0]["note_by"] == "손님"
    assert notes[0]["note"] in guests.NOTES_LOW + guests.NOTES_MID + guests.NOTES_HIGH
    assert notes[0]["parent_uid"] is not None and 4 <= notes[0]["x"] <= 5 and notes[0]["y"] == 2  # on the table
    # the note never scores, and taking it away refunds nothing
    inn = next(r for r in client.get("/api/rooms").json()["rooms"] if r["id"] == "inn")["comfort"]["inn"]
    assert inn["raw"] == 160
    before = _balance(client, lun)
    r = client.delete(f"/api/room/item/{notes[0]['uid']}", headers=auth(lun))
    assert r.status_code == 200 and _balance(client, lun) == before
    # three nights → only the newest two notes stay
    conn = connect()
    try:
        with transaction(conn):
            guests.settle(conn, client.app.state.catalog, cfg, t0 + 4 * DAY, random.Random(3), [], set())
    finally:
        conn.close()
    notes = [i for i in client.get("/api/room/inn").json()["items"] if i["placed_by"] == "$guest"]
    assert len(notes) == guests.MAX_GUEST_NOTES


def test_dev_settle_simulates_days(env, monkeypatch):
    """DEV_TOOLS=1 mounts /api/dev/settle: a night passes on demand, with forced reservation odds."""
    import importlib
    from app import config
    monkeypatch.setattr(config, "DEV_TOOLS", True)
    from fastapi.testclient import TestClient
    from app.main import create_app
    with TestClient(create_app()) as client:
        lun = register(client, "lun")
        _place(client, lun, "bed", 1, 2)
        before = _balance(client, lun)
        r = client.post("/api/dev/settle", json={"days": 1, "chance": 1.0, "seed": 7}, headers=auth(lun))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["paid"] > 0 and _balance(client, lun) == before + body["paid"]
        kinds = sorted(e["kind"] for e in body["events"])
        assert kinds == ["guest", "reserve"] and body["views"]["inn"]["reservation"] is not None
        # the same day again pays nothing; reset forgets everything and starts over
        assert client.post("/api/dev/settle", json={"days": 1}, headers=auth(lun)).json()["paid"] == 0
        r = client.post("/api/dev/settle", json={"days": 0, "reset": True}, headers=auth(lun)).json()
        assert r["paid"] == 0 and r["views"]["inn"]["reservation"] is None
        assert client.post("/api/dev/settle", json={"days": 2, "chance": 0}, headers=auth(lun)).json()["paid"] > 0
    importlib.reload(config)


def test_locked_rooms_take_no_guests(env):
    import importlib
    import json
    import sys
    p = env["rooms"] / "inn.json"
    room = json.loads(p.read_text(encoding="utf-8"))
    room["restore"] = [{"id": "a", "name": "a", "need": [{"type": "pool", "amount": 10_000}],
                        "reward": [{"type": "unlock", "room": "house_a"}]}]
    p.write_text(json.dumps(room, ensure_ascii=False), encoding="utf-8")
    importlib.reload(sys.modules["app.catalog"])
    from fastapi.testclient import TestClient
    from app.main import create_app
    with TestClient(create_app()) as client:
        register(client, "lun")
        body = client.get("/api/rooms").json()
        assert body["locked"] == ["house_a"]
        assert next(r for r in body["rooms"] if r["id"] == "house_a")["comfort"] is None
        assert _meta("guest_day:house_a") == 0
        # special guests wait for the gate place: ordinary guests come, reservations and the dog lover do not
        lun = register(client, "lun")
        _place(client, lun, "bed", 1, 2)
        cfg = load_config().model_copy(deep=True)
        cfg.reservation.chance = 1.0
        cfg.special_after = "house_a"
        _sql("DELETE FROM room_meta WHERE k = 'dog_month'")
        ev = []
        assert _settle(client, now() + DAY, cfg=cfg, events=ev) > 0
        assert [e["kind"] for e in ev] == ["guest"] and _sql("SELECT * FROM reservations") == []


def test_zones_are_separate_guest_units(env):
    """A room with zones: each zone scores its own items, needs its own bed, settles on its own key."""
    import importlib
    import json
    import sys
    p = env["rooms"] / "house_a.json"
    room = json.loads(p.read_text(encoding="utf-8"))
    room["zones"] = [{"id": "r1", "name": "1호실", "x": 0, "y": 1, "w": 3, "h": 4}, {"id": "r2", "name": "2호실", "x": 3, "y": 1, "w": 3, "h": 4}]
    p.write_text(json.dumps(room, ensure_ascii=False), encoding="utf-8")
    importlib.reload(sys.modules["app.catalog"])
    from fastapi.testclient import TestClient
    from app import guests
    from app.main import create_app
    with TestClient(create_app()) as client:
        lun = register(client, "lun")
        cfg = load_config().model_copy(deep=True)
        cfg.reservation.chance = 0.0
        today = guests.day_key(now(), cfg)
        assert _meta("guest_day:house_a:r1") == today and _meta("guest_day:house_a:r2") == today and _meta("guest_day:house_a") == 0
        house = next(r for r in client.get("/api/rooms").json()["rooms"] if r["id"] == "house_a")
        assert set(house["comfort"]) == {"house_a:r1", "house_a:r2"}
        assert house["comfort"]["house_a:r1"]["zone_name"] == "1호실" and house["comfort"]["house_a:r1"]["room"] == "house_a"
        # a bed and a table in r1, a lone chair in r2 (no bed): only r1 takes guests, r2's chair scores nowhere else
        _place(client, lun, "bed", 0, 2, room="house_a")
        _place(client, lun, "table", 0, 1, room="house_a")
        _place(client, lun, "chair", 4, 2, room="house_a")
        house = next(r for r in client.get("/api/rooms").json()["rooms"] if r["id"] == "house_a")
        r1, r2 = house["comfort"]["house_a:r1"], house["comfort"]["house_a:r2"]
        assert r1["beds"] == 1 and r1["guests"] == 1 and r1["raw"] == 160
        assert r2["beds"] == 0 and r2["guests"] == 0 and r2["raw"] == 50
        ev = []
        paid = _settle(client, now() + DAY, cfg=cfg, events=ev)
        assert paid == r1["pay"] > 0
        g = [e for e in ev if e["kind"] == "guest"]
        assert len(g) == 1 and g[0]["room_id"] == "house_a" and g[0]["data"]["zone"] == "r1"
        assert _sql("SELECT item_id FROM ledger WHERE kind = 'guest'") == [{"item_id": "room:house_a:r1"}]
