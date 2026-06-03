from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.config import ScarfConfig, Settings
from app.domain.models import Decision, MarketInfo, Side, SignalDecision
from app.services.signal_service import SignalService
from app.services.simulation_service import SimulationService
from app.storage.db import get_connection, init_db
from app.storage.repositories import PortfolioSnapshotRepository, SignalRepository


class DummySettings:
    fixed_trade_usdc = 100.0
    per_market_cap_usdc = 300.0
    max_slippage_pct = 2.0
    max_signal_age_minutes = 15
    max_trade_age_minutes = 60
    max_trade_age_at_fill_minutes = 60
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


def _insert_signal(conn, *, price=0.57, wallet='0x1', tx_hash='0xtx', side: Side = Side.BUY):
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
            side=side,
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


def test_simulation_service_allows_favorable_slippage(tmp_path: Path):
    db_path = tmp_path / 'favorable-slippage.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        _insert_signal(conn, price=0.60)

        result = SimulationService(
            conn,
            DummySettings(),
            DummyMarketService(DummyMarketClient(asks=[{'price': 0.50, 'size': 500.0}])),
        ).run()

        assert result.filled_count == 1
        row = conn.execute('SELECT status, reason, slippage_pct FROM sim_orders ORDER BY id DESC LIMIT 1').fetchone()
        assert row['status'] == 'filled'
        assert row['reason'] == 'filled'
        assert Decimal(str(row['slippage_pct'])) < 0


def test_simulation_service_accounts_for_realized_pnl_in_bankroll(tmp_path: Path):
    db_path = tmp_path / 'realized-bankroll.db'
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
        PortfolioSnapshotRepository(conn).insert(
            total_cost_basis=200.0,
            total_market_value=200.0,
            total_unrealized_pnl=0.0,
            total_realized_pnl=-100.0,
            total_equity=150.0,
            drawdown_pct=0.0,
            raw_json={'positions': []},
        )
        _insert_signal(conn)

        result = SimulationService(conn, BankrollSettings(), DummyMarketService()).run()

        assert result.rejected_count == 1
        row = conn.execute('SELECT status, reason FROM sim_orders ORDER BY id DESC LIMIT 1').fetchone()
        assert row['status'] == 'rejected'
        assert row['reason'] == 'bankroll_exceeded'


def test_simulation_service_rejects_unsupported_side(tmp_path: Path):
    db_path = tmp_path / 'unsupported-side.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        _insert_signal(conn, side=Side.SELL)

        result = SimulationService(conn, DummySettings(), DummyMarketService()).run()

        assert result.rejected_count == 1
        row = conn.execute('SELECT status, reason FROM sim_orders ORDER BY id DESC LIMIT 1').fetchone()
        assert row['status'] == 'rejected'
        assert row['reason'] == 'unsupported_side'


def test_simulation_service_rejects_stale_signal_by_detected_at(tmp_path: Path):
    db_path = tmp_path / 'stale-signal.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        _insert_signal(conn)
        stale_detected_at = (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()
        conn.execute('UPDATE signals SET detected_at = ?', (stale_detected_at,))
        conn.commit()

        result = SimulationService(conn, DummySettings(), DummyMarketService()).run()

        assert result.rejected_count == 1
        row = conn.execute('SELECT status, reason FROM sim_orders ORDER BY id DESC LIMIT 1').fetchone()
        assert row['status'] == 'rejected'
        assert row['reason'] == 'signal_stale'


def test_simulation_service_allows_fresh_signal_within_ttl(tmp_path: Path):
    db_path = tmp_path / 'fresh-signal.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        _insert_signal(conn)
        fresh_detected_at = (datetime.now(timezone.utc) - timedelta(minutes=14)).isoformat()
        conn.execute('UPDATE signals SET detected_at = ?', (fresh_detected_at,))
        conn.commit()

        result = SimulationService(conn, DummySettings(), DummyMarketService()).run()

        assert result.filled_count == 1
        row = conn.execute('SELECT status, reason FROM sim_orders ORDER BY id DESC LIMIT 1').fetchone()
        assert row['status'] == 'filled'
        assert row['reason'] == 'filled'


def test_simulation_service_rejects_unparseable_detected_at_as_stale(tmp_path: Path):
    db_path = tmp_path / 'bad-detected-at.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        _insert_signal(conn)
        conn.execute("UPDATE signals SET detected_at = 'not-a-date'")
        conn.commit()

        result = SimulationService(conn, DummySettings(), DummyMarketService()).run()

        assert result.rejected_count == 1
        row = conn.execute('SELECT status, reason FROM sim_orders ORDER BY id DESC LIMIT 1').fetchone()
        assert row['status'] == 'rejected'
        assert row['reason'] == 'signal_stale'


def test_simulation_service_ttl_window_treats_just_inside_limit_as_fresh(tmp_path: Path):
    db_path = tmp_path / 'ttl-boundary.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        _insert_signal(conn)
        exact_boundary = (datetime.now(timezone.utc) - timedelta(minutes=15) + timedelta(seconds=1)).isoformat()
        conn.execute('UPDATE signals SET detected_at = ?', (exact_boundary,))
        conn.commit()

        result = SimulationService(conn, DummySettings(), DummyMarketService()).run()

        assert result.filled_count == 1
        row = conn.execute('SELECT status, reason FROM sim_orders ORDER BY id DESC LIMIT 1').fetchone()
        assert row['status'] == 'filled'
        assert row['reason'] == 'filled'


def test_simulation_service_rejects_old_trade_even_when_signal_detection_is_fresh(tmp_path: Path):
    db_path = tmp_path / 'stale-trade-fresh-signal.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        _insert_signal(conn)
        stale_trade_time = (datetime.now(timezone.utc) - timedelta(minutes=61)).isoformat()
        fresh_detected_at = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        conn.execute('UPDATE leader_trades SET timestamp = ?', (stale_trade_time,))
        conn.execute('UPDATE signals SET detected_at = ?', (fresh_detected_at,))
        conn.commit()

        result = SimulationService(conn, DummySettings(), DummyMarketService()).run()

        assert result.rejected_count == 1
        row = conn.execute('SELECT status, reason FROM sim_orders ORDER BY id DESC LIMIT 1').fetchone()
        assert row['status'] == 'rejected'
        assert row['reason'] == 'trade_too_old_at_fill'


def test_simulation_service_uses_dedicated_fill_trade_age_limit(tmp_path: Path):
    db_path = tmp_path / 'dedicated-fill-trade-age.db'
    init_db(str(db_path))

    class DivergentAgeSettings(DummySettings):
        max_trade_age_minutes = 60
        max_trade_age_at_fill_minutes = 15

    with get_connection(str(db_path)) as conn:
        _insert_signal(conn)
        trade_time = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        detected_at = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        conn.execute('UPDATE leader_trades SET timestamp = ?', (trade_time,))
        conn.execute('UPDATE signals SET detected_at = ?', (detected_at,))
        conn.commit()

        result = SimulationService(conn, DivergentAgeSettings(), DummyMarketService()).run()

        assert result.rejected_count == 1
        row = conn.execute('SELECT status, reason FROM sim_orders ORDER BY id DESC LIMIT 1').fetchone()
        assert row['status'] == 'rejected'
        assert row['reason'] == 'trade_too_old_at_fill'


def test_settings_programmatic_fill_age_falls_back_to_trade_age():
    settings = Settings(
        app_env='test',
        db_path=':memory:',
        leaderboard_category='overall',
        leaderboard_time='30d',
        leaderboard_sort='profit',
        top_n=5,
        poll_interval_seconds=10,
        trade_fetch_limit=50,
        min_time_to_expiry_hours=24,
        min_market_liquidity=10000,
        signal_cooldown_minutes=5,
        max_trade_age_minutes=30,
    )

    assert settings.max_trade_age_at_fill_minutes is None
    assert settings.effective_max_trade_age_at_fill_minutes == 30


def test_signal_generation_can_accept_trade_that_fill_time_gate_rejects(tmp_path: Path):
    db_path = tmp_path / 'signal-accepts-fill-rejects.db'
    init_db(str(db_path))
    settings = Settings(
        app_env='test',
        db_path=str(db_path),
        leaderboard_category='overall',
        leaderboard_time='30d',
        leaderboard_sort='profit',
        top_n=5,
        poll_interval_seconds=10,
        trade_fetch_limit=50,
        min_time_to_expiry_hours=24,
        min_market_liquidity=10000,
        signal_cooldown_minutes=5,
        signal_batch_limit=500,
        max_trade_age_minutes=60,
        max_trade_age_at_fill_minutes=15,
        max_signal_age_minutes=15,
        fixed_trade_usdc=100.0,
        per_market_cap_usdc=300.0,
        max_slippage_pct=2.0,
        scarf_execution_mode='manual_confirm',
        scarf_bankroll_usd=1000.0,
        max_daily_orders=10,
    )

    with get_connection(str(db_path)) as conn:
        trade_timestamp = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        conn.execute(
            """
            INSERT INTO leader_trades (
                wallet, leader_name, transaction_hash, condition_id, asset_id, side,
                size, price, timestamp, market_title, market_slug, raw_json, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                '0x1', 'alice', '0xdivergent', 'cond1', 'asset_yes', 'BUY',
                10.0, 0.57, trade_timestamp,
                'Will X happen?', 'will-x-happen', '{}', datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()

        signal_result = SignalService(conn, settings, DummyMarketService()).run()
        assert signal_result.accepted_count == 1

        signal_row = conn.execute('SELECT decision, reason FROM signals ORDER BY id DESC LIMIT 1').fetchone()
        assert dict(signal_row) == {'decision': 'accepted', 'reason': 'accepted'}

        simulation_result = SimulationService(conn, settings, DummyMarketService()).run()
        assert simulation_result.rejected_count == 1

        sim_order = conn.execute('SELECT status, reason FROM sim_orders ORDER BY id DESC LIMIT 1').fetchone()
        assert dict(sim_order) == {'status': 'rejected', 'reason': 'trade_too_old_at_fill'}


def test_signal_repository_pending_rows_include_trade_timestamp(db_conn, insert_signal_for_trade):
    inserted, signal_row = insert_signal_for_trade()
    assert inserted is True

    pending = SignalRepository(db_conn).list_pending_accepted()

    assert len(pending) == 1
    assert pending[0]['id'] == signal_row['id']
    assert pending[0]['trade_timestamp'] is not None


def test_simulation_service_rejects_future_dated_detected_at(tmp_path: Path):
    db_path = tmp_path / 'future-detected-at.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        _insert_signal(conn)
        future_detected_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        conn.execute('UPDATE signals SET detected_at = ?', (future_detected_at,))
        conn.commit()

        result = SimulationService(conn, DummySettings(), DummyMarketService()).run()

        assert result.rejected_count == 1
        row = conn.execute('SELECT status, reason FROM sim_orders ORDER BY id DESC LIMIT 1').fetchone()
        assert dict(row) == {'status': 'rejected', 'reason': 'signal_timestamp_in_future'}


def test_simulation_service_rejects_future_dated_trade_timestamp(tmp_path: Path):
    db_path = tmp_path / 'future-trade-timestamp.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        _insert_signal(conn)
        future_trade_time = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        conn.execute('UPDATE leader_trades SET timestamp = ?', (future_trade_time,))
        conn.commit()

        result = SimulationService(conn, DummySettings(), DummyMarketService()).run()

        assert result.rejected_count == 1
        row = conn.execute('SELECT status, reason FROM sim_orders ORDER BY id DESC LIMIT 1').fetchone()
        assert dict(row) == {'status': 'rejected', 'reason': 'trade_timestamp_in_future'}


def test_simulation_service_rejects_orphan_signal_fail_closed(tmp_path: Path):
    db_path = tmp_path / 'orphan-signal.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        _insert_signal(conn)
        conn.execute('PRAGMA foreign_keys = OFF')
        conn.execute('DELETE FROM leader_trades')
        conn.execute('PRAGMA foreign_keys = ON')
        conn.commit()

        result = SimulationService(conn, DummySettings(), DummyMarketService()).run()

        assert result.rejected_count == 1
        row = conn.execute('SELECT status, reason FROM sim_orders ORDER BY id DESC LIMIT 1').fetchone()
        assert dict(row) == {'status': 'rejected', 'reason': 'trade_too_old_at_fill'}
