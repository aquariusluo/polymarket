from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path


def _schema_path() -> Path:
    return Path(__file__).with_name("schema.sql")


TARGET_TEXT_COLUMNS: dict[str, list[str]] = {
    "leader_trades": ["size", "price"],
    "markets": ["liquidity"],
    "signals": ["leader_price"],
    "sim_orders": [
        "requested_notional",
        "filled_notional",
        "filled_shares",
        "fill_price",
        "leader_price",
        "slippage_pct",
    ],
    "positions": ["shares", "avg_cost", "cost_basis"],
    "portfolio_snapshots": [
        "total_cost_basis",
        "total_market_value",
        "total_unrealized_pnl",
        "total_realized_pnl",
        "total_equity",
        "drawdown_pct",
    ],
}

_WARNED_DB_PATHS: set[str] = set()


def get_connection(db_path: str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if not path.exists():
        path.touch(mode=0o600)
    conn = sqlite3.connect(path, timeout=30.0)
    path.chmod(0o600)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    if db_path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


def decimal_storage_issues(conn: sqlite3.Connection) -> list[str]:
    issues: list[str] = []
    valid_tables = frozenset(TARGET_TEXT_COLUMNS.keys())
    for table, columns in TARGET_TEXT_COLUMNS.items():
        if table not in valid_tables:
            raise ValueError(f"Invalid table name: {table!r}")
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        if not rows:
            issues.append(f"{table}: missing table")
            continue
        types = {str(row[1]): str(row[2]).upper() for row in rows}
        for col in columns:
            t = types.get(col, "<missing>")
            if t != "TEXT":
                issues.append(f"{table}.{col}: expected TEXT, got {t}")
    return issues


def _enforce_or_warn_decimal_storage(conn: sqlite3.Connection, db_path: str) -> None:
    issues = decimal_storage_issues(conn)
    if not issues:
        return
    strict = os.getenv("DB_DECIMAL_SCHEMA_STRICT", "0").strip().lower() in {"1", "true", "yes", "on"}
    message = (
        f"Decimal storage health check failed for {db_path}. "
        "Run `python3 scripts/migrate_sqlite_decimal_text.py --db-path "
        f"{db_path}`. Issues: " + "; ".join(issues)
    )
    if strict:
        raise RuntimeError(message)
    if db_path not in _WARNED_DB_PATHS:
        print(f"WARNING: {message}", file=sys.stderr)
        _WARNED_DB_PATHS.add(db_path)


def init_db(db_path: str, conn: sqlite3.Connection | None = None) -> None:
    schema = _schema_path().read_text(encoding="utf-8")
    if conn is not None:
        conn.executescript(schema)
        conn.commit()
        _enforce_or_warn_decimal_storage(conn, db_path)
        return
    with get_connection(db_path) as db_conn:
        db_conn.executescript(schema)
        db_conn.commit()
        _enforce_or_warn_decimal_storage(db_conn, db_path)
