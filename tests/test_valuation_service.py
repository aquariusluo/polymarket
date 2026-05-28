from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx

from app.domain.models import MarketInfo
from app.services.valuation_service import ValuationService
from app.storage.db import get_connection, init_db


class DummySettings:
    pass


class DummyMarketClient:
    def __init__(self, books: dict[str, dict]):
        self.books = books

    def fetch_book(self, token_id: str):
        return self.books[token_id]


class DummyMarketService:
    def __init__(self, books: dict[str, dict]):
        self.market_client = DummyMarketClient(books)

    def get_market(self, condition_id: str) -> MarketInfo | None:
        return MarketInfo(
            condition_id=condition_id,
            title='Will X happen?',
            slug='will-x-happen',
            end_time=datetime.now(timezone.utc) + timedelta(days=2),
            liquidity=20000.0,
            active=True,
            closed=False,
            yes_token_id='asset_yes',
            no_token_id='asset_no',
            yes_outcome='Yes',
            no_outcome='No',
            raw_json={},
        )


def test_mark_to_market_creates_snapshot(tmp_path: Path):
    db_path = tmp_path / 'valuation.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO positions (
                condition_id, asset_id, market_slug, side, shares, avg_cost, cost_basis, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ('cond1', 'asset_yes', 'will-x-happen', 'BUY', 100.0, 0.40, 40.0, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()

        result = ValuationService(
            conn,
            DummySettings(),
            DummyMarketService({'asset_yes': {'bids': [{'price': 0.58, 'size': 1000}], 'asks': [{'price': 0.62, 'size': 1000}]}}),
        ).mark_to_market()

        assert result.positions_marked == 1
        assert result.snapshot_id is not None

        row = conn.execute('SELECT total_cost_basis, total_market_value, total_unrealized_pnl FROM portfolio_snapshots').fetchone()
        assert Decimal(str(row['total_cost_basis'])) == Decimal('40.00')
        assert Decimal(str(row['total_market_value'])) == Decimal('58.00')
        assert Decimal(str(row['total_unrealized_pnl'])) == Decimal('18.00')


def test_mark_to_market_uses_highest_bid(tmp_path: Path):
    db_path = tmp_path / 'valuation-best-bid.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO positions (
                condition_id, asset_id, market_slug, side, shares, avg_cost, cost_basis, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ('cond1', 'asset_yes', 'will-x-happen', 'BUY', 10.0, 0.40, 4.0, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()

        service = ValuationService(
            conn,
            DummySettings(),
            DummyMarketService(
                {
                    'asset_yes': {
                        'bids': [{'price': 0.51, 'size': 1000}, {'price': 0.59, 'size': 5}, {'price': 0.57, 'size': 800}],
                        'asks': [{'price': 0.62, 'size': 1000}],
                    }
                }
            ),
        )
        service.mark_to_market()
        row = conn.execute('SELECT total_market_value FROM portfolio_snapshots ORDER BY id DESC LIMIT 1').fetchone()
        assert Decimal(str(row['total_market_value'])) == Decimal('5.90')


def test_mark_to_market_carries_realized_and_skips_http_errors(tmp_path: Path):
    db_path = tmp_path / 'valuation-errors.db'
    init_db(str(db_path))

    class FlakyMarketClient:
        def fetch_book(self, token_id: str):
            if token_id == 'bad_asset':
                raise httpx.ReadTimeout('timeout')
            return {'bids': [{'price': 0.55, 'size': 1000}], 'asks': [{'price': 0.60, 'size': 1000}]}

    class FlakyMarketService:
        market_client = FlakyMarketClient()

    with get_connection(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO portfolio_snapshots (
                captured_at, total_cost_basis, total_market_value, total_unrealized_pnl,
                total_realized_pnl, total_equity, drawdown_pct, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (datetime.now(timezone.utc).isoformat(), '10.00', '11.00', '1.00', '3.25', '14.25', '0.0000', '{}'),
        )
        conn.execute(
            """
            INSERT INTO positions (
                condition_id, asset_id, market_slug, side, shares, avg_cost, cost_basis, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ('cond1', 'good_asset', 'm1', 'BUY', 10.0, 0.40, 4.0, datetime.now(timezone.utc).isoformat()),
        )
        conn.execute(
            """
            INSERT INTO positions (
                condition_id, asset_id, market_slug, side, shares, avg_cost, cost_basis, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ('cond2', 'bad_asset', 'm2', 'BUY', 10.0, 0.40, 4.0, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()

        result = ValuationService(conn, DummySettings(), FlakyMarketService()).mark_to_market()
        assert result.positions_marked == 1
        row = conn.execute(
            'SELECT total_realized_pnl, raw_json FROM portfolio_snapshots ORDER BY id DESC LIMIT 1'
        ).fetchone()
        assert Decimal(str(row['total_realized_pnl'])) == Decimal('3.25')
        assert 'mark_errors' in row['raw_json']


def test_mark_to_market_settles_closed_market_positions_into_realized(tmp_path: Path):
    db_path = tmp_path / 'valuation-settlement.db'
    init_db(str(db_path))

    class SettlingMarketService:
        class _Client:
            def fetch_book(self, token_id: str):
                return {'bids': [{'price': 0.52, 'size': 1000}], 'asks': [{'price': 0.58, 'size': 1000}]}

        market_client = _Client()

        def get_market(self, condition_id: str) -> MarketInfo | None:
            return MarketInfo(
                condition_id=condition_id,
                title='Settled market',
                slug='settled',
                end_time=datetime.now(timezone.utc) - timedelta(days=1),
                liquidity=10000.0,
                active=False,
                closed=True,
                yes_token_id='asset_yes',
                no_token_id='asset_no',
                yes_outcome='Yes',
                no_outcome='No',
                raw_json={
                    'clob': {
                        'tokens': [
                            {'token_id': 'asset_yes', 'outcome': 'Yes', 'winner': True, 'price': 1},
                            {'token_id': 'asset_no', 'outcome': 'No', 'winner': False, 'price': 0},
                        ]
                    }
                },
            )

    with get_connection(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO portfolio_snapshots (
                captured_at, total_cost_basis, total_market_value, total_unrealized_pnl,
                total_realized_pnl, total_equity, drawdown_pct, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (datetime.now(timezone.utc).isoformat(), '10.00', '12.00', '2.00', '1.00', '13.00', '0.0000', '{}'),
        )
        conn.execute(
            """
            INSERT INTO positions (
                condition_id, asset_id, market_slug, side, shares, avg_cost, cost_basis, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ('cond-settle', 'asset_yes', 'settled', 'BUY', 10.0, 0.40, 4.0, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()

        result = ValuationService(conn, DummySettings(), SettlingMarketService()).mark_to_market()
        assert result.positions_marked == 0
        assert conn.execute('SELECT COUNT(*) FROM positions').fetchone()[0] == 0
        snap = conn.execute(
            'SELECT total_realized_pnl, total_market_value, total_unrealized_pnl, raw_json FROM portfolio_snapshots ORDER BY id DESC LIMIT 1'
        ).fetchone()
        # prior realized 1.00 + (settled value 10.00 - cost 4.00) = 7.00
        assert Decimal(str(snap['total_realized_pnl'])) == Decimal('7.00')
        assert Decimal(str(snap['total_market_value'])) == Decimal('0.00')
        assert Decimal(str(snap['total_unrealized_pnl'])) == Decimal('0.00')
        assert 'settled_positions' in snap['raw_json']


def test_mark_to_market_settles_losing_position_to_zero(tmp_path: Path):
    db_path = tmp_path / 'valuation-settlement-loss.db'
    init_db(str(db_path))

    class SettlingLossMarketService:
        class _Client:
            def fetch_book(self, token_id: str):
                return {'bids': [{'price': 0.40, 'size': 1000}], 'asks': [{'price': 0.45, 'size': 1000}]}

        market_client = _Client()

        def get_market(self, condition_id: str) -> MarketInfo | None:
            return MarketInfo(
                condition_id=condition_id,
                title='Settled market',
                slug='settled',
                end_time=datetime.now(timezone.utc) - timedelta(days=1),
                liquidity=10000.0,
                active=False,
                closed=True,
                yes_token_id='asset_yes',
                no_token_id='asset_no',
                yes_outcome='Yes',
                no_outcome='No',
                raw_json={'clob': {'tokens': [{'token_id': 'asset_yes', 'outcome': 'Yes', 'winner': False, 'price': 0}]}},
            )

    with get_connection(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO portfolio_snapshots (
                captured_at, total_cost_basis, total_market_value, total_unrealized_pnl,
                total_realized_pnl, total_equity, drawdown_pct, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (datetime.now(timezone.utc).isoformat(), '10.00', '12.00', '2.00', '1.00', '13.00', '0.0000', '{}'),
        )
        conn.execute(
            """
            INSERT INTO positions (
                condition_id, asset_id, market_slug, side, shares, avg_cost, cost_basis, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ('cond-loss', 'asset_yes', 'settled', 'BUY', 10.0, 0.40, 4.0, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()

        ValuationService(conn, DummySettings(), SettlingLossMarketService()).mark_to_market()
        snap = conn.execute(
            'SELECT total_realized_pnl, total_market_value, total_unrealized_pnl FROM portfolio_snapshots ORDER BY id DESC LIMIT 1'
        ).fetchone()
        # prior realized 1.00 + (settled value 0.00 - cost 4.00) = -3.00
        assert Decimal(str(snap['total_realized_pnl'])) == Decimal('-3.00')
        assert Decimal(str(snap['total_market_value'])) == Decimal('0.00')
        assert Decimal(str(snap['total_unrealized_pnl'])) == Decimal('0.00')


def test_mark_to_market_closed_market_without_winner_falls_back_to_mark(tmp_path: Path):
    db_path = tmp_path / 'valuation-no-winner.db'
    init_db(str(db_path))

    class NoWinnerMarketService:
        class _Client:
            def fetch_book(self, token_id: str):
                return {'bids': [{'price': 0.60, 'size': 1000}], 'asks': [{'price': 0.65, 'size': 1000}]}

        market_client = _Client()

        def get_market(self, condition_id: str) -> MarketInfo | None:
            return MarketInfo(
                condition_id=condition_id,
                title='Closed unresolved',
                slug='closed-unresolved',
                end_time=datetime.now(timezone.utc) - timedelta(days=1),
                liquidity=10000.0,
                active=False,
                closed=True,
                yes_token_id='asset_yes',
                no_token_id='asset_no',
                yes_outcome='Yes',
                no_outcome='No',
                raw_json={'clob': {'tokens': [{'token_id': 'asset_yes', 'outcome': 'Yes'}]}},
            )

    with get_connection(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO positions (
                condition_id, asset_id, market_slug, side, shares, avg_cost, cost_basis, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ('cond-nowin', 'asset_yes', 'm', 'BUY', 10.0, 0.40, 4.0, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()

        result = ValuationService(conn, DummySettings(), NoWinnerMarketService()).mark_to_market()
        assert result.positions_marked == 1
        assert conn.execute('SELECT COUNT(*) FROM positions').fetchone()[0] == 1
        snap = conn.execute(
            'SELECT total_market_value, raw_json FROM portfolio_snapshots ORDER BY id DESC LIMIT 1'
        ).fetchone()
        assert Decimal(str(snap['total_market_value'])) == Decimal('6.00')
        assert 'settled_positions' in snap['raw_json']


def test_mark_to_market_closed_market_asset_not_in_tokens_falls_back_to_mark(tmp_path: Path):
    db_path = tmp_path / 'valuation-asset-missing.db'
    init_db(str(db_path))

    class MissingAssetTokenService:
        class _Client:
            def fetch_book(self, token_id: str):
                return {'bids': [{'price': 0.70, 'size': 1000}], 'asks': [{'price': 0.75, 'size': 1000}]}

        market_client = _Client()

        def get_market(self, condition_id: str) -> MarketInfo | None:
            return MarketInfo(
                condition_id=condition_id,
                title='Closed mismatch',
                slug='closed-mismatch',
                end_time=datetime.now(timezone.utc) - timedelta(days=1),
                liquidity=10000.0,
                active=False,
                closed=True,
                yes_token_id='other_yes',
                no_token_id='other_no',
                yes_outcome='Yes',
                no_outcome='No',
                raw_json={'clob': {'tokens': [{'token_id': 'other_yes', 'outcome': 'Yes', 'winner': True}]}},
            )

    with get_connection(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO positions (
                condition_id, asset_id, market_slug, side, shares, avg_cost, cost_basis, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ('cond-miss', 'asset_yes', 'm', 'BUY', 10.0, 0.40, 4.0, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()

        result = ValuationService(conn, DummySettings(), MissingAssetTokenService()).mark_to_market()
        assert result.positions_marked == 1
        assert conn.execute('SELECT COUNT(*) FROM positions').fetchone()[0] == 1
        snap = conn.execute(
            'SELECT total_market_value FROM portfolio_snapshots ORDER BY id DESC LIMIT 1'
        ).fetchone()
        assert Decimal(str(snap['total_market_value'])) == Decimal('7.00')
