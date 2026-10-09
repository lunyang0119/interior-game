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
    assert inn["comfort"]["beds"] == 0 and inn["comfort"]["guests"] == 0 and inn["comfort"]["reservation"] is None
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
    expect = inn["comfort"]["pay"]
    assert inn["comfort"]["beds"] == 1 and inn["comfort"]["guests"] == 1 and expect > 0
    cfg = load_config().model_copy(deep=True)
    cfg.reservation.chance = 0.0  # a random reservation would be missed during the catch-up and skip a night
    t0 = now()
    ev = []
    assert _settle(client, t0 + DAY, cfg=cfg, events=ev) == expect
    assert _balance(client, lun) == before + expect
    guest = [e for e in ev if e["kind"] == "guest"]
    assert len(guest) == 1 and guest[0]["room_id"] == "inn" and guest[0]["amount"] == expect
    assert guest[0]["data"]["guests"] == 1 and guest[0]["data"]["score"] == inn["comfort"]["score"]
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
    view = next(r for r in client.get("/api/rooms").json()["rooms"] if r["id"] == "inn")["comfort"]
    assert view["reservation"] == {"id": 1, "kind": "item", "item_id": "chair", "due_day": today + 1, "days_left": 1}
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
        view = guests.room_view(conn, cat, cat.rooms["inn"], cfg, t0 + DAY)
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
    view = next(r for r in client.get("/api/rooms").json()["rooms"] if r["id"] == "inn")["comfort"]
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
    assert len(row) == 1 and row[0]["room_id"] == "inn"
    due = row[0]["due_day"]
    view = next(r for r in client.get("/api/rooms").json()["rooms"] if r["id"] == "inn")["comfort"]
    days = due - guests.day_key(t0 + DAY, cfg)
    ev = []
    paid = _settle(client, t0 + (1 + days) * DAY, cfg=cfg, events=ev)
    g = [e for e in ev if e["kind"] == "guest" and e["data"].get("dog")]
    assert len(g) == 1 and g[0]["data"]["dog"] == round(view["per_guest"] * cfg.dog.pay_mult)
    assert paid >= g[0]["data"]["dog"]
    assert _sql("SELECT status FROM reservations WHERE kind = 'dog'")[0]["status"] == "paid"


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
