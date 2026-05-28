from __future__ import annotations

import inspect
from datetime import datetime, timezone
from decimal import Decimal

from app.storage.repositories import SimOrderRepository


def test_sim_order_repository_insert_has_explicit_parameters():
    params = list(inspect.signature(SimOrderRepository.insert).parameters)
    assert params == [
        'self',
        'signal_id',
        'condition_id',
        'asset_id',
        'market_slug',
        'side',
        'requested_notional',
        'filled_notional',
        'filled_shares',
        'fill_price',
        'leader_price',
        'slippage_pct',
        'status',
        'reason',
    ]


def test_sim_order_repository_insert_persists_row(db_conn):
    db_conn.execute(
        """
        INSERT INTO leader_trades (
            wallet, leader_name, transaction_hash, condition_id, asset_id, side,
            size, price, timestamp, market_title, market_slug, raw_json, ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            '0xrepo', 'repo', '0xrepo-tx', 'cond1', 'asset1', 'BUY',
            10.0, 0.49, datetime.now(timezone.utc).isoformat(), 'Repo Market', 'market-1', '{}',
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    leader_trade_id = db_conn.execute('SELECT id FROM leader_trades ORDER BY id DESC LIMIT 1').fetchone()[0]
    db_conn.execute(
        """
        INSERT INTO signals (
            leader_trade_id, wallet, leader_name, condition_id, asset_id, market_slug, side,
            leader_price, decision, reason, detected_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            leader_trade_id, '0xrepo', 'repo', 'cond1', 'asset1', 'market-1', 'BUY',
            0.49, 'accepted', 'accepted', datetime.now(timezone.utc).isoformat(), '{}',
        ),
    )
    signal_id = db_conn.execute('SELECT id FROM signals ORDER BY id DESC LIMIT 1').fetchone()[0]

    row_id = SimOrderRepository(db_conn).insert(
        signal_id=signal_id,
        condition_id='cond1',
        asset_id='asset1',
        market_slug='market-1',
        side='BUY',
        requested_notional=100.0,
        filled_notional=95.0,
        filled_shares=190.0,
        fill_price=0.5,
        leader_price=0.49,
        slippage_pct=2.04,
        status='filled',
        reason='filled',
    )

    assert row_id > 0
    row = db_conn.execute('SELECT * FROM sim_orders WHERE id = ?', (row_id,)).fetchone()
    assert row['condition_id'] == 'cond1'
    assert Decimal(str(row['filled_notional'])) == Decimal('95.00')
    assert row['status'] == 'filled'
