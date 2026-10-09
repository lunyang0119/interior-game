"""Notes: `note`-tagged items carry a text anyone can rewrite; other items refuse."""
from conftest import auth, register


def test_note_write_read_clear(env):
    from fastapi.testclient import TestClient
    from app.main import create_app

    with TestClient(create_app()) as client:
        lun = register(client, "lun")
        kim = register(client, "kim")
        uid = client.post("/api/room/place", json={"item_id": "memo", "x": 1, "y": 2}, headers=auth(lun)).json()["uid"]
        chair = client.post("/api/room/place", json={"item_id": "chair", "x": 3, "y": 2}, headers=auth(lun)).json()["uid"]
        v0 = client.get("/api/room/inn").json()["version"]

        r = client.put(f"/api/room/item/{uid}/note", json={"text": "  식탁 여기 어때?  "}, headers=auth(lun))
        assert r.status_code == 200 and r.json()["note"] == "식탁 여기 어때?" and r.json()["note_by"] == "lun"
        room = client.get("/api/room/inn").json()
        assert room["version"] == v0 + 1
        row = next(i for i in room["items"] if i["uid"] == uid)
        assert row["note"] == "식탁 여기 어때?" and row["note_by"] == "lun" and row["note_ts"] > 0
        # notes are shared: anyone rewrites
        assert client.put(f"/api/room/item/{uid}/note", json={"text": "좋아!"}, headers=auth(kim)).json()["note_by"] == "kim"
        # empty text clears
        r = client.put(f"/api/room/item/{uid}/note", json={"text": ""}, headers=auth(kim)).json()
        assert r["note"] is None and r["note_by"] is None
        # only note items
        assert client.put(f"/api/room/item/{chair}/note", json={"text": "x"}, headers=auth(lun)).status_code == 400
        assert client.put("/api/room/item/9999/note", json={"text": "x"}, headers=auth(lun)).status_code == 404
        # too long
        assert client.put(f"/api/room/item/{uid}/note", json={"text": "a" * 201}, headers=auth(lun)).status_code == 422
        # unauthenticated
        assert client.put(f"/api/room/item/{uid}/note", json={"text": "x"}).status_code == 401
