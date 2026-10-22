"""VM mode of the editor: blocked routes and the "게임에 반영" job (check → DB copy → restart)."""
import io
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import editor as E  # noqa: E402

NOOP = [sys.executable, "-c", "pass"]
FAIL = [sys.executable, "-c", "raise SystemExit(1)"]


def stub_restart(monkeypatch, tmp_path, active=NOOP):
    monkeypatch.setattr(E, "VM", True)
    monkeypatch.setattr(E, "APPLY_RESTART", NOOP)
    monkeypatch.setattr(E, "APPLY_ACTIVE", active)
    monkeypatch.setattr(E, "APPLY_JOURNAL", NOOP)
    monkeypatch.setattr(E, "APPLY_SETTLE_S", 0)
    monkeypatch.setattr(E, "APPLY_ENV_FILE", tmp_path / "no.env")
    monkeypatch.setattr(E, "APPLY_BACKUP_DIR", tmp_path / "backups")


def test_apply_checks_data_backs_up_db_and_restarts(tmp_path, monkeypatch):
    # the repo's own data/ must pass the server's boot checks (that is the check the job runs)
    db = tmp_path / "interior.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE t(x)")
    c.execute("INSERT INTO t VALUES (1)")
    c.commit()
    c.close()
    monkeypatch.setenv("DB_PATH", str(db))
    stub_restart(monkeypatch, tmp_path)
    job = E.ApplyJob()
    job._run()
    assert job.done and job.ok, "\n".join(job.lines)
    backups = list((tmp_path / "backups").glob("interior-*.db"))
    assert len(backups) == 1
    assert sqlite3.connect(backups[0]).execute("SELECT x FROM t").fetchone() == (1,)
    assert any("✔" in line for line in job.lines)


def test_apply_reports_a_server_that_did_not_come_up(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "missing.db"))
    stub_restart(monkeypatch, tmp_path, active=FAIL)
    job = E.ApplyJob()
    job._run()
    assert job.done and not job.ok
    assert any("안 떴어요" in line for line in job.lines)
    assert not (tmp_path / "backups").exists()  # no DB → nothing to copy


def test_apply_refuses_outside_vm_mode(monkeypatch):
    monkeypatch.setattr(E, "VM", False)
    assert E.start_apply()["ok"] is False


def test_dotenv_parses_key_values(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# comment\nDB_PATH=/opt/x.db\nQUOTED=\"a b\"\n\nBROKEN LINE\n", encoding="utf-8")
    assert E._dotenv(p) == {"DB_PATH": "/opt/x.db", "QUOTED": "a b"}
    assert E._dotenv(tmp_path / "none") == {}


class FakeHandler(E.Handler):
    """Handler without a socket: only vm_blocked / send_json are exercised."""

    def __init__(self):
        self.out = io.BytesIO()
        self.wfile = self.out
        self.status = None

    def send_response(self, code, message=None):
        self.status = code

    def send_header(self, *a):
        pass

    def end_headers(self):
        pass


def test_vm_blocked_routes(monkeypatch):
    monkeypatch.setattr(E, "VM", True)
    h = FakeHandler()
    assert h.vm_blocked("/api/build") is True
    assert h.status == 400 and "VM" in json.loads(h.out.getvalue())["error"]
    assert FakeHandler().vm_blocked("/api/items") is False
    monkeypatch.setattr(E, "VM", False)
    assert FakeHandler().vm_blocked("/api/build") is False
