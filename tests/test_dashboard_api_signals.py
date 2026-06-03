from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from dashboard.api.database import get_db
from dashboard.api.main import create_app
from app.storage.db import get_connection, init_db


def _seed_signal(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT INTO leader_trades (
            wallet, leader_name, transaction_hash, condition_id, asset_id, side,
            size, price, timestamp, market_title, market_slug, raw_json, ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            '0x1', 'alice', '0xsmoke', 'cond1', 'asset_yes', 'BUY',
            1.0, 0.5, datetime.now(timezone.utc).isoformat(),
            'Market', 'slug', '{}', datetime.now(timezone.utc).isoformat(),
        ),
    )
    trade_id = conn.execute(
        "SELECT id FROM leader_trades WHERE transaction_hash = '0xsmoke'"
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO signals (
            leader_trade_id, wallet, leader_name, condition_id, asset_id,
            market_slug, side, leader_price, decision, reason, detected_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            trade_id, '0x1', 'alice', 'cond1', 'asset_yes', 'slug', 'BUY', 0.5,
            'rejected', 'signal_stale', datetime.now(timezone.utc).isoformat(), '{}',
        ),
    )
    conn.commit()


def test_signals_endpoint_includes_reason_and_order_reason_fields(tmp_path, monkeypatch):
    db_path = tmp_path / 'api-smoke.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as seed_conn:
        _seed_signal(seed_conn)

    monkeypatch.delenv('DASHBOARD_API_TOKEN', raising=False)

    app = create_app()

    def override_get_db():
        conn = get_connection(str(db_path))
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = override_get_db

    client = TestClient(app)
    response = client.get('/api/signals')

    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    row = data[0]
    assert 'reason' in row, "'reason' field missing from /api/signals response"
    assert 'order_reason' in row, "'order_reason' field missing from /api/signals response"
    assert row['reason'] == 'signal_stale'
    assert row['order_reason'] is None
