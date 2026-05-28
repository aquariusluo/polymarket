from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.config import ScarfConfig
from app.domain.models import Decision, MarketInfo, Side, SignalDecision
from app.services.simulation_service import SimulationService
from app.storage.db import get_connection, init_db
from app.storage.repositories import SignalRepository


class DummySettings:
    fixed_trade_usdc = 100.0
    per_market_cap_usdc = 300.0
    max_slippage_pct = 2.0
    scarf = ScarfConfig(bankroll_usd=1000.0, max_daily_orders=10)


class DummyMarketClient:
    def __init__(self, asks=None, should_raise: bool = False, error: Exception | None = None):
        self.asks = asks or [{'price': 0.58, 'size': 500.0}]
        self.should_raise = should_raise
        self.error = error or httpx.ReadTimeout('book unavailable')

    def fetch_book(self, token_id: str):
        if self.should_raise:
            raise self.error
        return {
            'asks': self.asks,
            'bids': [
                {'price': 0.57, 'size': 500.0},
            ],
        }


class DummyMarketService:
    def __init__(self, market_client: DummyMarketClient | None = None):
        self.market_client = market_client or DummyMarketClient()

    def get_market(self, condition_id: str) -> MarketInfo | None:
        return MarketInfo(
            condition_id=condition_id,
            title='Will X happen?',
            slug='will-x-happen',
            end_time=datetime.now(timezone.utc) + timedelta(days=3),
            liquidity=25000.0,
            active=True,
            closed=False,
            yes_token_id='asset_yes',
            no_token_id='asset_no',
            yes_outcome='Yes',
            no_outcome='No',
            raw_json={},
        )


def _insert_signal(conn, *, price=0.57, wallet='0x1', tx_hash='0xtx'):
    conn.execute(
        """
        INSERT INTO leader_trades (
            wallet, leader_name, transaction_hash, condition_id, asset_id, side,
            size, price, timestamp, market_title, market_slug, raw_json, ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            wallet, 'alice', tx_hash, 'cond1', 'asset_yes', 'BUY',
            10.0, price, datetime.now(timezone.utc).isoformat(),
            'Will X happen?', 'will-x-happen', '{}', datetime.now(timezone.utc).isoformat(),
        ),
    )
    trade_id = conn.execute('SELECT id FROM leader_trades ORDER BY id DESC LIMIT 1').fetchone()[0]
    SignalRepository(conn).insert_if_new(
        type('T', (), {'wallet': '0x1', 'leader_name': 'alice', 'raw_json': {}})(),
        SignalDecision(
            leader_trade_id=trade_id,
            condition_id='cond1',
            asset_id='asset_yes',
            decision=Decision.ACCEPTED,
            reason='accepted',
            side=Side.BUY,
            price=price,
            market_slug='will-x-happen',
        ),
    )


def test_simulation_service_creates_order_and_position(tmp_path: Path):
    db_path = tmp_path / 'test.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        _insert_signal(conn)

        result = SimulationService(conn, DummySettings(), DummyMarketService()).run()
        assert result.processed_count == 1
        assert result.filled_count == 1
        assert conn.execute('SELECT COUNT(*) FROM sim_orders').fetchone()[0] == 1
        assert conn.execute('SELECT COUNT(*) FROM positions').fetchone()[0] == 1


def test_simulation_service_respects_top_of_book_depth(tmp_path: Path):
    db_path = tmp_path / 'depth.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        _insert_signal(conn)

        result = SimulationService(
            conn,
            DummySettings(),
            DummyMarketService(DummyMarketClient(asks=[{'price': 0.58, 'size': 30.0}])),
        ).run()

        assert result.filled_count == 1
        row = conn.execute('SELECT filled_notional, filled_shares FROM sim_orders').fetchone()
        assert Decimal(str(row['filled_notional'])) == Decimal('17.40')
        assert Decimal(str(row['filled_shares'])) == Decimal('30.000000')


def test_simulation_service_rejects_missing_leader_price(tmp_path: Path):
    db_path = tmp_path / 'missing-price.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        _insert_signal(conn, price=None)

        result = SimulationService(conn, DummySettings(), DummyMarketService()).run()

        assert result.rejected_count == 1
        row = conn.execute('SELECT status, reason FROM sim_orders').fetchone()
        assert row['status'] == 'rejected'
        assert row['reason'] == 'missing_leader_price'


def test_simulation_service_records_book_unavailable_rejection(tmp_path: Path):
    db_path = tmp_path / 'book-unavailable.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        _insert_signal(conn)

        result = SimulationService(
            conn,
            DummySettings(),
            DummyMarketService(DummyMarketClient(should_raise=True)),
        ).run()

        assert result.rejected_count == 1
        row = conn.execute('SELECT status, reason FROM sim_orders').fetchone()
        assert row['status'] == 'rejected'
        assert row['reason'] == 'book_unavailable'


def test_simulation_service_enforces_per_market_cap_across_assets(tmp_path: Path):
    db_path = tmp_path / 'market-cap.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO positions (
                condition_id, asset_id, market_slug, side, shares, avg_cost, cost_basis, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                'cond1', 'asset_no', 'will-x-happen', 'BUY', 100.0, 3.0, 300.0,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        _insert_signal(conn)

        result = SimulationService(conn, DummySettings(), DummyMarketService()).run()

        assert result.rejected_count == 1
        row = conn.execute('SELECT status, reason FROM sim_orders').fetchone()
        assert row['status'] == 'rejected'
        assert row['reason'] == 'per_market_cap_exceeded'


def test_simulation_service_caps_to_remaining_market_capacity(tmp_path: Path):
    db_path = tmp_path / 'remaining-cap.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO positions (
                condition_id, asset_id, market_slug, side, shares, avg_cost, cost_basis, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                'cond1', 'asset_no', 'will-x-happen', 'BUY', 100.0, 2.8, 280.0,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        _insert_signal(conn)

        result = SimulationService(
            conn,
            DummySettings(),
            DummyMarketService(DummyMarketClient(asks=[{'price': 0.58, 'size': 500.0}])),
        ).run()

        assert result.filled_count == 1
        row = conn.execute('SELECT filled_notional, filled_shares FROM sim_orders').fetchone()
        assert Decimal(str(row['filled_notional'])) == Decimal('20.00')
        assert Decimal(str(row['filled_shares'])) == Decimal('34.482759')


def test_simulation_service_surfaces_unexpected_book_errors(tmp_path: Path):
    db_path = tmp_path / 'unexpected-book-error.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        _insert_signal(conn)

        with pytest.raises(ValueError, match='bad parser state'):
            SimulationService(
                conn,
                DummySettings(),
                DummyMarketService(DummyMarketClient(should_raise=True, error=ValueError('bad parser state'))),
            ).run()



def test_simulation_service_rejects_when_daily_order_limit_reached(tmp_path: Path):
    db_path = tmp_path / 'daily-cap.db'
    init_db(str(db_path))

    class DailyCapSettings(DummySettings):
        scarf = ScarfConfig(bankroll_usd=1000.0, max_daily_orders=1)

    with get_connection(str(db_path)) as conn:
        _insert_signal(conn, wallet='0xfilled', tx_hash='0xfilled')
        existing_signal_id = conn.execute('SELECT id FROM signals ORDER BY id ASC LIMIT 1').fetchone()[0]
        conn.execute(
            """
            INSERT INTO sim_orders (
                signal_id, condition_id, asset_id, market_slug, side,
                requested_notional, filled_notional, filled_shares, fill_price,
                leader_price, slippage_pct, status, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                existing_signal_id, 'existing-cond', 'existing-asset', 'existing-market', 'BUY',
                50.0, 50.0, 100.0, 0.5, 0.5, 0.0, 'filled', 'filled',
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        _insert_signal(conn, wallet='0xpending', tx_hash='0xpending')

        result = SimulationService(conn, DailyCapSettings(), DummyMarketService()).run()

        assert result.rejected_count == 1
        row = conn.execute('SELECT status, reason FROM sim_orders ORDER BY id DESC LIMIT 1').fetchone()
        assert row['status'] == 'rejected'
        assert row['reason'] == 'max_daily_orders_exceeded'


def test_simulation_service_rejects_when_bankroll_would_be_exceeded(tmp_path: Path):
    db_path = tmp_path / 'bankroll-cap.db'
    init_db(str(db_path))

    class BankrollSettings(DummySettings):
        scarf = ScarfConfig(bankroll_usd=250.0, max_daily_orders=10)

    with get_connection(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO positions (
                condition_id, asset_id, market_slug, side, shares, avg_cost, cost_basis, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                'cond-existing', 'asset-existing', 'market-existing', 'BUY', 150.0, 1.0, 200.0,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        _insert_signal(conn)

        result = SimulationService(conn, BankrollSettings(), DummyMarketService()).run()

        assert result.rejected_count == 1
        row = conn.execute('SELECT status, reason FROM sim_orders ORDER BY id DESC LIMIT 1').fetchone()
        assert row['status'] == 'rejected'
        assert row['reason'] == 'bankroll_exceeded'



def test_simulation_service_rejects_slippage_too_high(tmp_path: Path):
    db_path = tmp_path / 'slippage.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        _insert_signal(conn, price=0.50)

        result = SimulationService(
            conn,
            DummySettings(),
            DummyMarketService(DummyMarketClient(asks=[{'price': 0.60, 'size': 500.0}])),
        ).run()

        assert result.rejected_count == 1
        row = conn.execute('SELECT status, reason FROM sim_orders ORDER BY id DESC LIMIT 1').fetchone()
        assert row['status'] == 'rejected'
        assert row['reason'] == 'slippage_too_high'
