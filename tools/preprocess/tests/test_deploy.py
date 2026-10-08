import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import deploy as D  # noqa: E402


def make_repo(tmp: Path) -> Path:
    (tmp / "data" / "rooms").mkdir(parents=True)
    (tmp / "data" / "rooms" / "inn.json").write_text("{}")
    (tmp / "data" / "items.json").write_text("{}")
    (tmp / "client" / "public" / "gen").mkdir(parents=True)
    (tmp / "client" / "public" / "gen" / "interiors.png").write_bytes(b"png")
    (tmp / "server" / "static").mkdir(parents=True)
    (tmp / "server" / "static" / "index.html").write_text("<html>")
    return tmp


def test_status_groups_changes_and_restart(tmp_path):
    root = make_repo(tmp_path)
    state = tmp_path / "state.json"
    s = D.status(root, state)
    assert s["never"] and s["count"] == 0
    D.mark(root, state)
    s = D.status(root, state)
    assert s["count"] == 0 and not s["restart"] and not s["never"]

    (root / "client" / "public" / "gen" / "interiors.png").write_bytes(b"png2")  # atlas only: no restart
    s = D.status(root, state)
    assert [g["folder"] for g in s["groups"]] == ["client/public/gen"]
    assert s["groups"][0]["files"][0]["kind"] == "changed" and not s["restart"]

    (root / "data" / "rooms" / "floor_2.json").write_text("{}")  # new room: restart
    (root / "data" / "rooms" / "inn.json").unlink()
    s = D.status(root, state)
    rooms = next(g for g in s["groups"] if g["folder"] == "data/rooms")
    assert {f["name"]: f["kind"] for f in rooms["files"]} == {"floor_2.json": "new", "inn.json": "deleted"}
    assert rooms["restart"] and s["restart"] and rooms["vm"] == "/opt/interior/data/rooms"

    D.mark(root, state)
    assert D.status(root, state)["count"] == 0
    assert set(json.loads(state.read_text())["files"]) == {"data/rooms/floor_2.json", "data/items.json",
                                                            "client/public/gen/interiors.png", "server/static/index.html"}


def test_bundle_stale(tmp_path):
    root = make_repo(tmp_path)
    assert not D.bundle_stale(root)
    (root / "client" / "src").mkdir()
    import time; time.sleep(0.01)
    (root / "client" / "src" / "main.ts").write_text("x")
    assert D.bundle_stale(root)
