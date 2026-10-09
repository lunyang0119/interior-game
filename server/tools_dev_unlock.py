"""Local dev helper: mark the inn's restoration stages complete so floor_2 / room2 open.

    .\\.venv\\Scripts\\python.exe tools_dev_unlock.py          # stage:inn = 2 (floor_2 + room2 open)
    .\\.venv\\Scripts\\python.exe tools_dev_unlock.py reset    # back to stage 0

Runs against DB_PATH from server/.env (default interior.db). Never run on the VM.
"""
import sqlite3
import sys
from pathlib import Path

env = Path(__file__).with_name(".env")
db = "interior.db"
if env.exists():
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("DB_PATH="):
            db = line.split("=", 1)[1].strip()
conn = sqlite3.connect(Path(__file__).parent / db)  # relative paths resolve next to this file (like the server)
if len(sys.argv) > 1 and sys.argv[1] == "reset":
    conn.execute("DELETE FROM room_meta WHERE k LIKE 'stage:%' OR k LIKE 'stage_ts:%'")
    print("stages reset")
else:
    conn.execute("INSERT OR REPLACE INTO room_meta(k, v) VALUES ('stage:inn', 2)")
    print("stage:inn = 2 → floor_2 and room2 unlocked (reload the browser)")
conn.commit()
