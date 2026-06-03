from __future__ import annotations

import inspect
from decimal import Decimal
from pathlib import Path

from app.config import ScarfConfig
from app.services import job_run_service, market_service, reporting_service, simulation_service, valuation_service
from app.services.simulation_service import SimulationService
from app.services.valuation_service import ValuationService
from app.storage.db import get_connection, init_db
from app.storage.repositories import PositionRepository


class DummySimulationSettings:
    fixed_trade_usdc = 0.30
    per_market_cap_usdc = 10.0
    max_slippage_pct = 15.0
    max_trade_age_minutes = 60
    max_trade_age_at_fill_minutes = 60
    scarf = ScarfConfig(bankroll_usd=10.0, max_daily_orders=10)


class DummyMarketClient:
    def fetch_book(self, token_id: str):
        return {
            'asks': [{'price': 0.10, 'size': 3.0}],
            'bids': [{'price': 0.09, 'size': 3.0}],
        }


class DummyMarketService:
    def __init__(self):
        self.market_client = DummyMarketClient()


def _seed_pending_signal(conn) -> None:
    conn.execute(
        """
        INSERT INTO leader_trades (
            wallet, leader_name, transaction_hash, condition_id, asset_id, side,
            size, price, timestamp, market_title, market_slug, raw_json, ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?, ?, datetime('now'))
        """,
        ('0x1', 'alice', '0xtx-decimal', 'cond1', 'asset_yes', 'BUY', 3.0, 0.09, 'Will X happen?', 'slug', '{}'),
    )
    trade_id = conn.execute('SELECT id FROM leader_trades ORDER BY id DESC LIMIT 1').fetchone()[0]
    conn.execute(
        """
        INSERT INTO signals (
            leader_trade_id, wallet, leader_name, condition_id, asset_id,
            market_slug, side, leader_price, decision, reason, detected_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)
        """,
        (trade_id, '0x1', 'alice', 'cond1', 'asset_yes', 'slug', 'BUY', 0.09, 'accepted', 'accepted', '{}'),
    )
    conn.commit()


def test_position_repository_rounds_cost_basis_and_average_cost(tmp_path: Path):
    db_path = tmp_path / 'position-rounding.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        repo = PositionRepository(conn)
        repo.upsert_buy('cond1', 'asset1', 'slug', 'BUY', shares=3.0, fill_price=0.1)
        repo.upsert_buy('cond1', 'asset1', 'slug', 'BUY', shares=1.0, fill_price=0.2)

        pos = repo.get('cond1', 'asset1')
        assert pos is not None
        assert Decimal(str(pos.cost_basis)) == Decimal('0.50')
        assert Decimal(str(pos.avg_cost)) == Decimal('0.125000')


def test_simulation_service_rounds_partial_fill_notional_and_shares(tmp_path: Path):
    db_path = tmp_path / 'simulation-rounding.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        _seed_pending_signal(conn)
        result = SimulationService(conn, DummySimulationSettings(), DummyMarketService()).run()

        row = conn.execute('SELECT filled_notional, filled_shares, fill_price, slippage_pct FROM sim_orders').fetchone()
        assert result.filled_count == 1
        assert Decimal(str(row['filled_notional'])) == Decimal('0.30')
        assert Decimal(str(row['filled_shares'])) == Decimal('3.000000')
        assert Decimal(str(row['fill_price'])) == Decimal('0.100000')
        assert Decimal(str(row['slippage_pct'])) == Decimal('11.1111')


def test_valuation_service_rounds_bid_mark_and_snapshot_totals(tmp_path: Path):
    db_path = tmp_path / 'valuation-rounding.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO positions (
                condition_id, asset_id, market_slug, side, shares, avg_cost, cost_basis, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            ('cond1', 'asset_yes', 'slug', 'BUY', 3.0, 0.10, 0.30),
        )
        conn.commit()

        result = ValuationService(conn, object(), DummyMarketService()).mark_to_market()
        row = conn.execute('SELECT total_cost_basis, total_market_value, total_unrealized_pnl FROM portfolio_snapshots').fetchone()
        assert result.positions_marked == 1
        assert Decimal(str(row['total_cost_basis'])) == Decimal('0.30')
        assert Decimal(str(row['total_market_value'])) == Decimal('0.27')
        assert Decimal(str(row['total_unrealized_pnl'])) == Decimal('-0.03')


def test_service_constructor_annotations_are_explicit():
    expectations = [
        (market_service.MarketService.__init__, ['conn', 'settings']),
        (reporting_service.ReportingService.__init__, ['conn', 'settings']),
        (valuation_service.ValuationService.__init__, ['conn', 'settings']),
        (simulation_service.SimulationService.__init__, ['conn', 'settings']),
        (job_run_service.execute_job, ['conn']),
    ]
    for fn, names in expectations:
        sig = inspect.signature(fn)
        for name in names:
            assert sig.parameters[name].annotation is not inspect._empty
