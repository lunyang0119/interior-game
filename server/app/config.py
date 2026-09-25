"""Runtime configuration from environment variables."""

import os
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVER_DIR.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines, # comments, optional quotes. Real env vars win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_dotenv(SERVER_DIR / ".env")


def _env_path(name: str, default: Path) -> Path:
    v = os.environ.get(name)
    return Path(v) if v else default


DB_PATH = _env_path("DB_PATH", SERVER_DIR / "interior.db")
DATA_DIR = _env_path("DATA_DIR", REPO_ROOT / "data")
GEN_DIR = _env_path("GEN_DIR", REPO_ROOT / "client" / "public" / "gen")
STATIC_DIR = _env_path("STATIC_DIR", SERVER_DIR / "static")

# Apps Script web-app URL. Never sent to clients.
SHEET_URL = os.environ.get("SHEET_URL", "")
# Local JSON with the same shape as the Apps Script response; used when SHEET_URL is empty.
FAKE_SHEET_PATH = _env_path("FAKE_SHEET_PATH", DATA_DIR / "fake_sheet.json")
SHEET_CACHE_SECONDS = int(os.environ.get("SHEET_CACHE_SECONDS", "60"))
SHEET_SYNC_COOLDOWN_SECONDS = int(os.environ.get("SHEET_SYNC_COOLDOWN_SECONDS", "30"))

IP_SALT = os.environ.get("IP_SALT", "dev-salt-change-me")

# Rate limits: (requests, per_seconds)
RATE_PLAYER = (120, 60)
RATE_REGISTER_IP = (5, 60)
