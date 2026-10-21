import json

from conftest import auth, recv, register


def test_clean():
    from app import chat
    assert chat.clean("  안녕   하세요 \n\n\n\n 반가워요  ") == "안녕 하세요\n\n반가워요"
    assert chat.clean("") is None and chat.clean("   \n ") is None and chat.clean(None) is None and chat.clean(3) is None
    assert chat.clean("a\x00b\x07c") == "abc"
    assert len(chat.clean("x" * 500)) == chat.MAX_LEN


def test_chat_roundtrip(client):
    lun = register(client, "lun")
    kim = register(client, "kim")
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        a.send_text(json.dumps({"type": "auth", "token": lun}))
        assert a.receive_json()["type"] == "hello"
        b.send_text(json.dumps({"type": "auth", "token": kim}))
        assert b.receive_json()["type"] == "hello"
        assert recv(a, "join")["id"] == "kim"
        # kim walks out to the map, then talks: everyone gets it, tagged with the map as the room
        b.send_text(json.dumps({"type": "enter", "room": "map", "x": 1, "y": 1}))
        assert recv(b, "entered")["room"] == "map"
        assert recv(a, "leave")["id"] == "kim"
        b.send_text(json.dumps({"type": "chat", "text": "  여기 바깥이에요  "}))
        ma = recv(a, "chat")
        mb = recv(b, "chat")
        assert ma == mb
        assert ma["player"] == "kim" and ma["room"] == "map" and ma["text"] == "여기 바깥이에요" and ma["id"] == 1 and ma["ts"] > 0
        # blank / non-string messages are dropped silently
        b.send_text(json.dumps({"type": "chat", "text": "   "}))
        b.send_text(json.dumps({"type": "chat", "text": 5}))
        b.send_text(json.dumps({"type": "chat", "text": "둘째"}))
        assert recv(a, "chat")["text"] == "둘째"
    # history: oldest first, newest HISTORY only
    r = client.get("/api/chat", headers=auth(lun))
    assert r.status_code == 200
    body = r.json()
    assert [m["text"] for m in body["messages"]] == ["여기 바깥이에요", "둘째"] and body["max_len"] == 200
    assert client.get("/api/chat").status_code == 401


def test_chat_rate_limit(client):
    from app import chat
    lun = register(client, "lun")
    with client.websocket_connect("/ws") as a:
        a.send_text(json.dumps({"type": "auth", "token": lun}))
        assert a.receive_json()["type"] == "hello"
        n = chat.RATE_LIMIT[0]
        for i in range(n + 1):
            a.send_text(json.dumps({"type": "chat", "text": f"m{i}"}))
        got = [recv(a, ("chat", "error")) for _ in range(n + 1)]
        assert [m["type"] for m in got] == ["chat"] * n + ["error"]
        assert got[-1]["code"] == "rate_limited"
    assert len(client.get("/api/chat", headers=auth(lun)).json()["messages"]) == n


def test_chat_history_cap(client):
    from app import chat
    lun = register(client, "lun")
    from app.db import connect, transaction
    conn = connect()
    with transaction(conn):
        for i in range(chat.HISTORY + 7):
            chat.store(conn, "lun", "inn", f"m{i}")
    conn.close()
    msgs = client.get("/api/chat", headers=auth(lun)).json()["messages"]
    assert len(msgs) == chat.HISTORY and msgs[0]["text"] == "m7" and msgs[-1]["text"] == f"m{chat.HISTORY + 6}"
