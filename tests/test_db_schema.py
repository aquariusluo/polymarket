from pathlib import Path

import pytest

from app.storage.db import get_connection, init_db


def test_init_db_creates_tables(tmp_path: Path):
    db_path = tmp_path / "test.db"
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        names = {row["name"] for row in rows}

    assert "leaders" in names
    assert "leader_trades" in names
    assert "job_runs" in names
    assert "markets" in names
    assert "signals" in names
    assert "sim_orders" in names
    assert "positions" in names
    assert "portfolio_snapshots" in names


def test_runtime_connections_enforce_foreign_keys(tmp_path: Path):
    db_path = tmp_path / "fk.db"
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        with pytest.raises(Exception):
            conn.execute(
                """
                INSERT INTO signals (
                    leader_trade_id, wallet, leader_name, condition_id, asset_id,
                    market_slug, side, leader_price, decision, reason, detected_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)
                """,
                (999999, "0x1", "alice", "cond1", "asset_yes", "slug", "BUY", 0.55, "accepted", "accepted", "{}"),
            )


def test_runtime_connections_enable_wal_and_busy_timeout(tmp_path: Path):
    db_path = tmp_path / "wal.db"
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]

    assert journal_mode == "wal"
    assert busy_timeout == 30000


def test_memory_connection_does_not_create_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)

    with get_connection(":memory:") as conn:
        database_path = conn.execute("PRAGMA database_list").fetchone()["file"]
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]

    assert database_path == ""
    assert busy_timeout == 30000
    assert not (tmp_path / ":memory:").exists()
