from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.config import Settings, get_settings
from app.domain.models import Leader, LeaderTrade, MarketInfo, SignalDecision
from app.storage.db import get_connection, init_db
from app.storage.repositories import LeaderTradeRepository, PortfolioSnapshotRepository, SignalRepository


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "test.db"
    init_db(str(path))
    return path


@pytest.fixture
def db_conn(db_path: Path):
    with get_connection(str(db_path)) as conn:
        yield conn


@pytest.fixture
def settings_factory():
    def _make(db_path: str, **overrides) -> Settings:
        base = dict(
            app_env='test',
            db_path=str(db_path),
            data_source='http',
            leaderboard_category='overall',
            leaderboard_time='30d',
            leaderboard_sort='profit',
            top_n=5,
            poll_interval_seconds=0,
            trade_fetch_limit=50,
            min_time_to_expiry_hours=24,
            min_market_liquidity=10000.0,
            signal_cooldown_minutes=5,
            signal_batch_limit=500,
            max_trade_age_minutes=60,
            max_trade_age_at_fill_minutes=60,
            fixed_trade_usdc=100.0,
            per_market_cap_usdc=300.0,
            max_slippage_pct=2.0,
            max_signal_age_minutes=15,
            market_cache_ttl_seconds=300,
            run_loop_max_iterations=1,
            run_loop_sleep_seconds=0,
            scarf_execution_mode='manual_confirm',
            scarf_bankroll_usd=1000.0,
            max_daily_orders=10,
        )
        base.update(overrides)
        return Settings(**base)

    return _make


@pytest.fixture
def settings(db_path: Path, settings_factory) -> Settings:
    return settings_factory(str(db_path))


@pytest.fixture
def sample_leader() -> Leader:
    return Leader(
        rank=1,
        wallet='0xleader',
        name='Alice',
        pseudonym='alice',
        pnl_snapshot=123.45,
        volume_snapshot=456.78,
        raw_json={'wallet': '0xleader'},
    )


@pytest.fixture
def sample_trade() -> LeaderTrade:
    return LeaderTrade(
        wallet='0xleader',
        leader_name='alice',
        transaction_hash='0xtx',
        condition_id='cond-1',
        asset_id='asset-1',
        side='BUY',
        size=10.0,
        price=0.62,
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=1),
        market_title='Will X happen?',
        market_slug='will-x-happen',
        raw_json={'tx': '0xtx'},
    )


@pytest.fixture
def sample_market() -> MarketInfo:
    return MarketInfo(
        condition_id='cond-1',
        title='Will X happen?',
        slug='will-x-happen',
        end_time=datetime.now(timezone.utc) + timedelta(days=7),
        liquidity=25000.0,
        active=True,
        closed=False,
        yes_token_id='yes-1',
        no_token_id='no-1',
        yes_outcome='Yes',
        no_outcome='No',
        raw_json={'condition_id': 'cond-1'},
        refreshed_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_signal_decision() -> SignalDecision:
    return SignalDecision(
        leader_trade_id=1,
        condition_id='cond-1',
        asset_id='asset-1',
        decision='accepted',
        reason='accepted',
        side='BUY',
        price=0.62,
        market_slug='will-x-happen',
    )


@pytest.fixture
def insert_signal_for_trade(db_conn, sample_trade):
    def _insert(*, decision: str = 'accepted', reason: str = 'accepted', detected_at: str | None = None):
        trade_repo = LeaderTradeRepository(db_conn)
        assert trade_repo.insert_if_new(sample_trade) is True
        trade_row = db_conn.execute('SELECT * FROM leader_trades ORDER BY id DESC LIMIT 1').fetchone()
        signal_decision = SignalDecision(
            leader_trade_id=int(trade_row['id']),
            condition_id=str(trade_row['condition_id']),
            asset_id=str(trade_row['asset_id']),
            decision=decision,
            reason=reason,
            side=trade_row['side'],
            price=float(trade_row['price']) if trade_row['price'] is not None else None,
            market_slug=trade_row['market_slug'],
        )
        signal_repo = SignalRepository(db_conn)
        inserted = signal_repo.insert_if_new(sample_trade, signal_decision)
        signal_row = db_conn.execute('SELECT * FROM signals ORDER BY id DESC LIMIT 1').fetchone()
        if detected_at is not None:
            db_conn.execute('UPDATE signals SET detected_at = ? WHERE id = ?', (detected_at, signal_row['id']))
            db_conn.commit()
            signal_row = db_conn.execute('SELECT * FROM signals WHERE id = ?', (signal_row['id'],)).fetchone()
        return inserted, signal_row

    return _insert


@pytest.fixture
def insert_snapshot(db_conn):
    repo = PortfolioSnapshotRepository(db_conn)

    def _insert(*, total_cost_basis: float = 100.0, total_market_value: float = 110.0, total_unrealized_pnl: float = 10.0, total_realized_pnl: float = 0.0, total_equity: float = 110.0, drawdown_pct: float = 0.0, raw_json: dict | None = None):
        return repo.insert(
            total_cost_basis=total_cost_basis,
            total_market_value=total_market_value,
            total_unrealized_pnl=total_unrealized_pnl,
            total_realized_pnl=total_realized_pnl,
            total_equity=total_equity,
            drawdown_pct=drawdown_pct,
            raw_json=raw_json or {'positions': []},
        )

    return _insert
