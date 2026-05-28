from __future__ import annotations

import json
from pathlib import Path

from app.config import get_settings
from app.storage.db import get_connection, init_db

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def read_json_report(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return {}


def get_db():
    settings = get_settings(str(PROJECT_ROOT))
    conn = get_connection(settings.db_path)
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
