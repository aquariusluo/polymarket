#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


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


CREATE_TABLE_SQL: dict[str, str] = {
    "leader_trades": """
CREATE TABLE leader_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet TEXT NOT NULL,
    leader_name TEXT,
    transaction_hash TEXT NOT NULL,
    condition_id TEXT,
    asset_id TEXT NOT NULL,
    side TEXT,
    size TEXT,
    price TEXT,
    timestamp TEXT NOT NULL,
    market_title TEXT,
    market_slug TEXT,
    raw_json TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    UNIQUE(wallet, transaction_hash, asset_id, timestamp, side)
)
""",
    "markets": """
CREATE TABLE markets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT NOT NULL UNIQUE,
    title TEXT,
    slug TEXT,
    end_time TEXT,
    liquidity TEXT,
    active INTEGER NOT NULL DEFAULT 0,
    closed INTEGER NOT NULL DEFAULT 0,
    yes_token_id TEXT,
    no_token_id TEXT,
    yes_outcome TEXT,
    no_outcome TEXT,
    raw_json TEXT NOT NULL,
    refreshed_at TEXT NOT NULL
)
""",
    "signals": """
CREATE TABLE signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    leader_trade_id INTEGER NOT NULL UNIQUE,
    wallet TEXT NOT NULL,
    leader_name TEXT,
    condition_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    market_slug TEXT,
    side TEXT,
    leader_price TEXT,
    decision TEXT NOT NULL,
    reason TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    raw_json TEXT,
    FOREIGN KEY (leader_trade_id) REFERENCES leader_trades(id)
)
""",
    "sim_orders": """
CREATE TABLE sim_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER NOT NULL UNIQUE,
    condition_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    market_slug TEXT,
    side TEXT,
    requested_notional TEXT NOT NULL,
    filled_notional TEXT,
    filled_shares TEXT,
    fill_price TEXT,
    leader_price TEXT,
    slippage_pct TEXT,
    status TEXT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (signal_id) REFERENCES signals(id)
)
""",
    "positions": """
CREATE TABLE positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    market_slug TEXT,
    side TEXT,
    shares TEXT NOT NULL,
    avg_cost TEXT NOT NULL,
    cost_basis TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(condition_id, asset_id)
)
""",
    "portfolio_snapshots": """
CREATE TABLE portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at TEXT NOT NULL,
    total_cost_basis TEXT NOT NULL,
    total_market_value TEXT NOT NULL,
    total_unrealized_pnl TEXT NOT NULL,
    total_realized_pnl TEXT NOT NULL,
    total_equity TEXT NOT NULL,
    drawdown_pct TEXT NOT NULL,
    raw_json TEXT NOT NULL
)
""",
}


def _table_column_types(conn: sqlite3.Connection, table: str) -> dict[str, str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]): str(row[2]).upper() for row in rows}


def verify(conn: sqlite3.Connection) -> tuple[bool, list[str]]:
    issues: list[str] = []
    for table, cols in TARGET_TEXT_COLUMNS.items():
        current = _table_column_types(conn, table)
        if not current:
            issues.append(f"{table}: missing table")
            continue
        for col in cols:
            t = current.get(col, "<missing>")
            if t != "TEXT":
                issues.append(f"{table}.{col}: expected TEXT, got {t}")
    return (len(issues) == 0, issues)


def _copy_sql(table: str, conn: sqlite3.Connection) -> str:
    cols = [str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    select_parts: list[str] = []
    for c in cols:
        if c in TARGET_TEXT_COLUMNS.get(table, []):
            select_parts.append(f"CAST({c} AS TEXT) AS {c}")
        else:
            select_parts.append(c)
    return f"INSERT INTO {table} ({', '.join(cols)}) SELECT {', '.join(select_parts)} FROM {table}__old"


def _migrate_table(conn: sqlite3.Connection, table: str) -> None:
    conn.execute(f"ALTER TABLE {table} RENAME TO {table}__old")
    conn.execute(CREATE_TABLE_SQL[table].strip())
    conn.execute(_copy_sql(table, conn))
    conn.execute(f"DROP TABLE {table}__old")


def migrate(conn: sqlite3.Connection) -> list[str]:
    migrated: list[str] = []
    for table in TARGET_TEXT_COLUMNS:
        current = _table_column_types(conn, table)
        if not current:
            continue
        needs = any(current.get(col, "") != "TEXT" for col in TARGET_TEXT_COLUMNS[table])
        if not needs:
            continue
        _migrate_table(conn, table)
        migrated.append(table)
    return migrated


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate SQLite monetary/price columns to TEXT storage.")
    parser.add_argument("--db-path", default="data/app.db", help="Path to SQLite database")
    parser.add_argument("--verify-only", action="store_true", help="Only verify column types, do not mutate")
    parser.add_argument("--no-backup", action="store_true", help="Skip automatic .bak copy")
    args = parser.parse_args()

    db_path = Path(args.db_path).expanduser().resolve()
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    if not args.verify_only and not args.no_backup:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = db_path.with_suffix(db_path.suffix + f".bak-{ts}")
        shutil.copy2(db_path, backup_path)
        print(f"Backup created: {backup_path}")

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        if args.verify_only:
            ok, issues = verify(conn)
            if ok:
                print("OK: all target columns are TEXT")
                return 0
            print("Verification issues:")
            for i in issues:
                print(f"- {i}")
            return 2

        conn.execute("BEGIN")
        migrated = migrate(conn)
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")
        fk_issues = conn.execute("PRAGMA foreign_key_check").fetchall()
        ok, issues = verify(conn)
        if fk_issues:
            print("Foreign key issues detected after migration:")
            for row in fk_issues:
                print(f"- {row}")
            return 3
        if not ok:
            print("Post-migration verification issues:")
            for i in issues:
                print(f"- {i}")
            return 4
        if migrated:
            print("Migrated tables:")
            for t in migrated:
                print(f"- {t}")
        else:
            print("No migration needed: all target columns already TEXT")
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
