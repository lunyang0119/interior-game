"""What has to go to the VM since the last upload.

The VM is updated by copying files over SFTP by hand (no git pull), which is easy to get wrong: a room file
stays behind, an atlas is uploaded without its manifest, the server is not restarted after a data change.
This module remembers a hash of every deployable file at the moment the user says "올렸음" (mark) and
reports which of them changed since, grouped by the folder they live in, plus whether the server has to be
restarted (it loads data/ and gen/manifest.json only at startup).

The state file lives next to this module and is gitignored: it describes one PC's upload history.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import config as C

STATE_FILE = Path(__file__).with_name(".deploy_state.json")
VM_ROOT = "/opt/interior"

# (folder relative to the repo, glob, needs a restart, note). Order = display order.
# server/static/gen and /media are copies vite makes of client/public; the VM serves /gen and /media from
# client/public, so only the page + bundle are listed for server/static.
TARGETS: list[tuple[str, str, bool, str]] = [
    ("server/app", "**/*.py", True, "서버 코드"),
    ("server/migrations", "*.sql", True, "DB 마이그레이션"),
    ("data/rooms", "*.json", True, "방 (seed는 재시작 때 자동으로 다시 심음)"),
    ("data", "items.json", True, "가구 카탈로그"),
    ("data", "map.json", True, "오버월드"),
    ("data", "dock.json", True, "부두"),
    ("data", "fishing.json", True, "낚시"),
    ("client/public/gen", "manifest.json", True, "슬라이스 목록 (서버가 시작할 때 읽음)"),
    ("client/public/gen", "*.png", False, "아틀라스"),
    ("client/public/gen", "interiors.json", False, "아틀라스 프레임"),
    ("client/public/gen", "map.json", False, "맵 아틀라스 프레임"),
    ("client/public/gen", "dock.json", False, "부두 레이아웃"),
    ("client/public/gen/chars", "**/*.png", False, "캐릭터"),
    ("client/public/gen/dock", "*.png", False, "부두 배경"),
    ("client/public/gen/mapbg", "*.png", False, "맵 배경"),
    ("client/public/gen/fish", "*.png", False, "물고기 아이콘"),
    ("client/public/media", "theme.css", False, "UI 테마"),
    ("client/public/media", "*.json", False, "BGM/SFX 목록"),
    ("client/public/media/ui", "*.png", False, "UI 프레임"),
    ("client/public/media/fonts", "*.ttf", False, "폰트"),
    ("client/public/media/bgm", "**/*.mp3", False, "BGM"),
    ("client/public/media/sfx", "**/*.mp3", False, "효과음"),
    ("server/static", "index.html", False, "클라이언트 페이지 (npm run build)"),
    ("server/static/assets", "*", False, "클라이언트 번들 (npm run build)"),
]

# (size, mtime_ns) → sha1, so a poll only rehashes files that were rewritten (media is ~80MB)
_hash_cache: dict[str, tuple[tuple[int, int], str]] = {}


def _sha1(p: Path) -> str:
    st = p.stat()
    sig = (st.st_size, st.st_mtime_ns)
    key = str(p)
    hit = _hash_cache.get(key)
    if hit and hit[0] == sig:
        return hit[1]
    h = hashlib.sha1()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    _hash_cache[key] = (sig, h.hexdigest())
    return _hash_cache[key][1]


def scan(root: Path | None = None) -> dict[str, dict]:
    """rel path → {"hash", "restart", "note"} for every deployable file that exists."""
    root = root or C.REPO_ROOT
    out: dict[str, dict] = {}
    for folder, pattern, restart, note in TARGETS:
        base = root / folder
        if not base.is_dir():
            continue
        for p in sorted(base.glob(pattern)):
            if not p.is_file() or p.name.startswith("."):
                continue
            rel = p.relative_to(root).as_posix()
            if rel in out:
                continue
            out[rel] = {"hash": _sha1(p), "restart": restart, "note": note}
    return out


def load_state(path: Path | None = None) -> dict:
    path = path or STATE_FILE
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"marked_at": None, "files": {}}


def mark(root: Path | None = None, path: Path | None = None) -> dict:
    """Remember the current hashes: everything on disk is now what the VM has."""
    files = scan(root)
    state = {"marked_at": int(time.time()), "files": {rel: f["hash"] for rel, f in files.items()}}
    (path or STATE_FILE).write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")
    return state


def bundle_stale(root: Path | None = None) -> bool:
    """client/src is newer than the built page → `npm run build` has not been run since the last source edit."""
    root = root or C.REPO_ROOT
    built = root / "server" / "static" / "index.html"
    if not built.exists():
        return True
    src = root / "client" / "src"
    if not src.is_dir():
        return False
    newest = max((p.stat().st_mtime for p in src.rglob("*") if p.is_file()), default=0)
    return newest > built.stat().st_mtime


def status(root: Path | None = None, path: Path | None = None) -> dict:
    """Changed / new / deleted deployable files since mark(), grouped by folder, with the restart verdict."""
    files = scan(root)
    state = load_state(path)
    known: dict[str, str] = state.get("files", {})
    never = state.get("marked_at") is None
    groups: dict[str, dict] = {}

    def add(rel: str, kind: str, restart: bool, note: str) -> None:
        folder = rel.rsplit("/", 1)[0] if "/" in rel else "."
        g = groups.setdefault(folder, {"folder": folder, "vm": f"{VM_ROOT}/{folder}", "restart": False, "files": []})
        g["files"].append({"name": rel.rsplit("/", 1)[-1], "kind": kind, "note": note})
        g["restart"] = g["restart"] or restart

    for rel, f in files.items():
        if never or rel not in known:
            add(rel, "new", f["restart"], f["note"])
        elif known[rel] != f["hash"]:
            add(rel, "changed", f["restart"], f["note"])
    for rel in known:
        if rel not in files:
            restart = any(rel.startswith(folder + "/") and r for folder, _, r, _ in TARGETS)
            add(rel, "deleted", restart, "VM에서도 지우기")

    # never marked: listing every file is noise; say so instead
    if never:
        groups = {}
    out = [groups[k] for k in sorted(groups)]
    return {
        "never": never,
        "marked_at": state.get("marked_at"),
        "groups": out,
        "count": sum(len(g["files"]) for g in out),
        "restart": any(g["restart"] for g in out),
        "bundle_stale": bundle_stale(root),
    }
