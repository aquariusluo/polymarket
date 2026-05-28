from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.services.reporting_service import ReportingService
from app.storage.db import get_connection, init_db


class DummySettings:
    db_path = ''


def _insert_trade(conn, *, tx_hash: str, condition_id: str, asset_id: str) -> int:
    conn.execute(
        """
        INSERT INTO leader_trades (
            wallet, leader_name, transaction_hash, condition_id, asset_id, side,
            size, price, timestamp, market_title, market_slug, raw_json, ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ('0x1', 'alice', tx_hash, condition_id, asset_id, 'BUY', 10.0, 0.55, datetime.now(timezone.utc).isoformat(), 'Will X happen?', 'slug', '{}', datetime.now(timezone.utc).isoformat()),
    )
    return conn.execute('SELECT last_insert_rowid()').fetchone()[0]


def _insert_snapshot(conn, *, equity: float, drawdown_pct: float, unrealized: float = 0.0, cost_basis: float = 100.0, market_value: float | None = None):
    if market_value is None:
        market_value = equity
    conn.execute(
        """
        INSERT INTO portfolio_snapshots (
            captured_at, total_cost_basis, total_market_value,
            total_unrealized_pnl, total_realized_pnl, total_equity, drawdown_pct, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (datetime.now(timezone.utc).isoformat(), cost_basis, market_value, unrealized, 0.0, equity, drawdown_pct, '{"positions": []}'),
    )


def test_generate_daily_report_includes_snapshot_and_execution_counts(tmp_path: Path):
    db_path = tmp_path / 'daily-reports.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO signals (
                leader_trade_id, wallet, leader_name, condition_id, asset_id,
                market_slug, side, leader_price, decision, reason, detected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (_insert_trade(conn, tx_hash='0xtx1', condition_id='cond1', asset_id='asset_yes'), '0x1', 'alice', 'cond1', 'asset_yes', 'slug', 'BUY', 0.55, 'accepted', 'accepted', datetime.now(timezone.utc).isoformat(), '{}'),
        )
        conn.execute(
            """
            INSERT INTO signals (
                leader_trade_id, wallet, leader_name, condition_id, asset_id,
                market_slug, side, leader_price, decision, reason, detected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (_insert_trade(conn, tx_hash='0xtx2', condition_id='cond1', asset_id='asset_yes'), '0x1', 'alice', 'cond1', 'asset_yes', 'slug', 'BUY', 0.55, 'accepted', 'accepted', datetime.now(timezone.utc).isoformat(), '{}'),
        )
        conn.execute(
            """
            INSERT INTO sim_orders (
                signal_id, condition_id, asset_id, market_slug, side, requested_notional,
                filled_notional, filled_shares, fill_price, leader_price, slippage_pct,
                status, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1, 'cond1', 'asset_yes', 'slug', 'BUY', 100.0, 98.0, 175.0, 0.56, 0.55, 1.81, 'filled', 'accepted', datetime.now(timezone.utc).isoformat()),
        )
        conn.execute(
            """
            INSERT INTO positions (
                condition_id, asset_id, market_slug, side, shares, avg_cost, cost_basis, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ('cond1', 'asset_yes', 'slug', 'BUY', 175.0, 0.56, 98.0, datetime.now(timezone.utc).isoformat()),
        )
        _insert_snapshot(conn, equity=125.0, drawdown_pct=0.0, unrealized=27.0, cost_basis=98.0, market_value=125.0)
        conn.commit()

        daily = ReportingService(conn, DummySettings()).generate_daily_report()

        assert daily['total_equity'] == 125.0
        assert daily['snapshot_count'] == 1
        assert daily['open_position_count'] == 1
        assert daily['accepted_signal_count'] == 2
        assert daily['filled_order_count'] == 1
        assert daily['rejected_order_count'] == 0


def test_generate_final_report_includes_return_and_max_drawdown(tmp_path: Path):
    db_path = tmp_path / 'final-reports.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        _insert_snapshot(conn, equity=100.0, drawdown_pct=0.0)
        _insert_snapshot(conn, equity=80.0, drawdown_pct=20.0)
        _insert_snapshot(conn, equity=125.0, drawdown_pct=0.0)
        conn.execute(
            """
            INSERT INTO signals (
                leader_trade_id, wallet, leader_name, condition_id, asset_id,
                market_slug, side, leader_price, decision, reason, detected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (_insert_trade(conn, tx_hash='0xtx2', condition_id='cond1', asset_id='asset_yes'), '0x1', 'alice', 'cond1', 'asset_yes', 'slug', 'BUY', 0.55, 'accepted', 'accepted', datetime.now(timezone.utc).isoformat(), '{}'),
        )
        conn.execute(
            """
            INSERT INTO signals (
                leader_trade_id, wallet, leader_name, condition_id, asset_id,
                market_slug, side, leader_price, decision, reason, detected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (_insert_trade(conn, tx_hash='0xtx3', condition_id='cond2', asset_id='asset_yes'), '0x1', 'alice', 'cond2', 'asset_yes', 'slug2', 'BUY', 0.55, 'accepted', 'accepted', datetime.now(timezone.utc).isoformat(), '{}'),
        )
        conn.execute(
            """
            INSERT INTO sim_orders (
                signal_id, condition_id, asset_id, market_slug, side, requested_notional,
                filled_notional, filled_shares, fill_price, leader_price, slippage_pct,
                status, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1, 'cond1', 'asset_yes', 'slug', 'BUY', 100.0, 98.0, 175.0, 0.56, 0.55, 1.81, 'filled', 'accepted', datetime.now(timezone.utc).isoformat()),
        )
        conn.execute(
            """
            INSERT INTO sim_orders (
                signal_id, condition_id, asset_id, market_slug, side, requested_notional,
                filled_notional, filled_shares, fill_price, leader_price, slippage_pct,
                status, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (2, 'cond2', 'asset_yes', 'slug2', 'BUY', 100.0, 0.0, 0.0, None, 0.55, None, 'rejected', 'book_unavailable', datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()

        final = ReportingService(conn, DummySettings()).generate_final_report()

        assert final['snapshot_count'] == 3
        assert final['period_start'] is not None
        assert final['period_end'] is not None
        assert final['open_position_count'] == 0
        assert final['starting_equity'] == 100.0
        assert final['ending_equity'] == 125.0
        assert final['net_pnl'] == 25.0
        assert final['return_pct'] == 25.0
        assert final['max_drawdown_pct'] == 20.0
        assert final['filled_order_count'] == 1
        assert final['rejected_order_count'] == 1



def test_reporting_repositories_support_snapshot_and_order_summary_queries(tmp_path: Path):
    from app.storage.repositories import PortfolioSnapshotRepository, SimOrderRepository

    db_path = tmp_path / 'reporting-repositories.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        _insert_snapshot(conn, equity=100.0, drawdown_pct=0.0)
        _insert_snapshot(conn, equity=80.0, drawdown_pct=20.0)
        _insert_snapshot(conn, equity=125.0, drawdown_pct=0.0)
        signal_one_trade_id = _insert_trade(conn, tx_hash='0xrepo1', condition_id='cond1', asset_id='asset_yes')
        signal_two_trade_id = _insert_trade(conn, tx_hash='0xrepo2', condition_id='cond2', asset_id='asset_yes')
        conn.execute(
            """
            INSERT INTO signals (
                leader_trade_id, wallet, leader_name, condition_id, asset_id,
                market_slug, side, leader_price, decision, reason, detected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (signal_one_trade_id, '0x1', 'alice', 'cond1', 'asset_yes', 'slug', 'BUY', 0.55, 'accepted', 'accepted', datetime.now(timezone.utc).isoformat(), '{}'),
        )
        conn.execute(
            """
            INSERT INTO signals (
                leader_trade_id, wallet, leader_name, condition_id, asset_id,
                market_slug, side, leader_price, decision, reason, detected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (signal_two_trade_id, '0x1', 'alice', 'cond2', 'asset_yes', 'slug2', 'BUY', 0.55, 'accepted', 'accepted', datetime.now(timezone.utc).isoformat(), '{}'),
        )
        conn.execute(
            """
            INSERT INTO sim_orders (
                signal_id, condition_id, asset_id, market_slug, side, requested_notional,
                filled_notional, filled_shares, fill_price, leader_price, slippage_pct,
                status, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1, 'cond1', 'asset_yes', 'slug', 'BUY', 100.0, 98.0, 175.0, 0.56, 0.55, 1.81, 'filled', 'accepted', datetime.now(timezone.utc).isoformat()),
        )
        conn.execute(
            """
            INSERT INTO sim_orders (
                signal_id, condition_id, asset_id, market_slug, side, requested_notional,
                filled_notional, filled_shares, fill_price, leader_price, slippage_pct,
                status, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (2, 'cond2', 'asset_yes', 'slug2', 'BUY', 100.0, 0.0, 0.0, None, 0.55, None, 'rejected', 'book_unavailable', datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()

        snapshot_repo = PortfolioSnapshotRepository(conn)
        order_repo = SimOrderRepository(conn)

        assert snapshot_repo.count() == 3
        assert snapshot_repo.first() is not None
        assert snapshot_repo.first().total_equity == 100.0
        assert snapshot_repo.latest() is not None
        assert snapshot_repo.latest().total_equity == 125.0
        assert snapshot_repo.max_drawdown_pct() == 20.0
        assert order_repo.count_by_status('filled') == 1
        assert order_repo.count_by_status('rejected') == 1
