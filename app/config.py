import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_env():
    envfile = ROOT / ".env"
    if not envfile.exists():
        return
    for line in envfile.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_env()

SECRET = os.environ.get("LIFTLOG_SECRET", "")
DB_PATH = os.environ.get("LIFTLOG_DB", str(ROOT / "liftlog.db"))
