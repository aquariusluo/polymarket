from __future__ import annotations

from pathlib import Path

from app.config import get_settings
from app.storage.db import get_connection, init_db

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_db():
    settings = get_settings(str(PROJECT_ROOT))
    conn = get_connection(settings.db_path)
    try:
        yield conn
    finally:
        conn.close()
