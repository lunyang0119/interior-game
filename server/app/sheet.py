"""Currency source: Apps Script doGet → {"members": [{"id": str, "earned": int}, ...]}.

The URL never leaves the server. Successful fetches are written to sheet_snapshot so
balances can still be computed when the script is unreachable (or after a restart).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time

import httpx

from . import config
from .db import now, transaction
from .errors import ApiError

log = logging.getLogger("sheet")


class SheetService:
    def __init__(self, url: str = "", fake_path=None, cache_seconds: int = 60, cooldown_seconds: int = 30,
                 secret: str = ""):
        self.url = url
        self.secret = secret
        self.fake_path = fake_path
        self.cache_seconds = cache_seconds
        self.cooldown_seconds = cooldown_seconds
        self._last_fetch = 0.0
        self._last_manual = 0.0
        self._lock = threading.Lock()

    # -- fetching -----------------------------------------------------------

    def _fetch(self) -> list[dict]:
        if self.url:
            r = httpx.get(self.url, timeout=10.0, follow_redirects=True)
            r.raise_for_status()
            data = r.json()
        else:
            data = json.loads(self.fake_path.read_text(encoding="utf-8"))
        members = data["members"]
        out = []
        for m in members:
            pid = str(m["id"]).strip()
            if not pid:
                continue
            out.append({"id": pid, "earned": int(m.get("earned") or 0)})
        return out

    def register(self, conn: sqlite3.Connection, player_id: str) -> dict:
        """Ask the sheet to record this id (column R), creating a row if the nickname is unknown.

        Returns the Apps Script response ({ok, id, created, earned}). Raises ApiError(503) on failure.
        The snapshot is force-refreshed afterwards so the new member is visible immediately.
        """
        try:
            if self.url:
                r = httpx.post(self.url, json={"action": "register", "id": player_id, "secret": self.secret},
                               timeout=15.0, follow_redirects=True)
                r.raise_for_status()
                data = r.json()
            else:
                data = self._fake_register(player_id)
        except Exception as e:
            log.warning("sheet register failed: %s", e)
            raise ApiError(503, "sheet_unavailable")
        if not data.get("ok"):
            log.warning("sheet register refused: %s", data)
            err = data.get("error")
            if err == "ambiguous":
                raise ApiError(409, "ambiguous_nickname")
            if err == "taken":
                raise ApiError(409, "nickname_taken")
            raise ApiError(503, "sheet_unavailable")
        with self._lock:
            self._last_fetch = 0.0
        self.refresh(conn, force=True)
        return data

    def _fake_register(self, player_id: str) -> dict:
        """Mirror of Code.gs doPost against fake_sheet.json (members may carry an optional "name")."""
        def norm(v) -> str:
            return "".join(str(v or "").split()).lower()

        key = norm(player_id)
        data = json.loads(self.fake_path.read_text(encoding="utf-8"))
        members = data["members"]
        exact = next((m for m in members if norm(m["id"]) == key or norm(m.get("name")) == key), None)
        partial = [m for m in members if key in norm(m.get("name", m["id"]))]
        m = exact or (partial[0] if len(partial) == 1 else None)
        if m is None and len(partial) > 1:
            return {"ok": False, "error": "ambiguous"}
        if m is not None:
            name = m.get("name", m["id"])
            if m.get("registered") and norm(m["id"]) != key:
                return {"ok": False, "error": "taken", "name": name}
            m.setdefault("name", m["id"])
            m["id"] = player_id
            m["registered"] = True
            self.fake_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            return {"ok": True, "id": player_id, "name": name, "created": False, "earned": int(m.get("earned") or 0)}
        members.append({"id": player_id, "name": player_id, "earned": 0, "registered": True})
        self.fake_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return {"ok": True, "id": player_id, "name": player_id, "created": True, "earned": 0}

    def refresh(self, conn: sqlite3.Connection, force: bool = False) -> bool:
        """Fetch if the cache is stale (or force). Returns True on a successful fetch."""
        with self._lock:
            age = time.monotonic() - self._last_fetch
            if not force and self._last_fetch and age < self.cache_seconds:
                return False
            try:
                members = self._fetch()
            except Exception as e:  # network / parse errors: keep the snapshot
                log.warning("sheet fetch failed: %s", e)
                return False
            ts = now()
            # the sheet may hold several rows with the same nickname (template/duplicate rows): merge them
            merged: dict[str, int] = {}
            for m in members:
                if m["id"] in merged:
                    log.warning("sheet: duplicate id %r, summing earned", m["id"])
                merged[m["id"]] = merged.get(m["id"], 0) + int(m["earned"])
            with transaction(conn):
                conn.execute("DELETE FROM sheet_snapshot")
                conn.executemany(
                    "INSERT INTO sheet_snapshot(player_id, earned, fetched_ts) VALUES (?, ?, ?)",
                    [(pid, earned, ts) for pid, earned in merged.items()],
                )
            self._last_fetch = time.monotonic()
            return True

    def manual_sync(self, conn: sqlite3.Connection) -> bool:
        if time.monotonic() - self._last_manual < self.cooldown_seconds:
            return False
        self._last_manual = time.monotonic()
        return self.refresh(conn, force=True)

    # -- queries (all from snapshot; no network) ----------------------------

    @staticmethod
    def has_snapshot(conn: sqlite3.Connection) -> bool:
        return conn.execute("SELECT 1 FROM sheet_snapshot LIMIT 1").fetchone() is not None

    @staticmethod
    def is_member(conn: sqlite3.Connection, player_id: str) -> bool:
        return conn.execute("SELECT 1 FROM sheet_snapshot WHERE player_id = ?", (player_id,)).fetchone() is not None

    @staticmethod
    def balance(conn: sqlite3.Connection) -> int:
        earned = conn.execute("SELECT COALESCE(SUM(earned), 0) FROM sheet_snapshot").fetchone()[0]
        spent = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM ledger").fetchone()[0]
        return int(earned) - int(spent)

    @staticmethod
    def contributions(conn: sqlite3.Connection) -> list[dict]:
        rows = conn.execute("SELECT player_id, earned FROM sheet_snapshot ORDER BY earned DESC, player_id").fetchall()
        return [{"id": r["player_id"], "earned": r["earned"]} for r in rows]

    def require_snapshot(self, conn: sqlite3.Connection) -> None:
        self.refresh(conn)
        if not self.has_snapshot(conn):
            raise ApiError(503, "sheet_unavailable")


def from_config() -> SheetService:
    return SheetService(
        url=config.SHEET_URL,
        fake_path=config.FAKE_SHEET_PATH,
        cache_seconds=config.SHEET_CACHE_SECONDS,
        cooldown_seconds=config.SHEET_SYNC_COOLDOWN_SECONDS,
        secret=config.SHEET_SECRET,
    )
