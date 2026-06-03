from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.clients.base_client import PolymarketUpstreamError
from app.jobs import (
    run_daily_report,
    run_final_report,
    run_generate_signals,
    run_mark_to_market,
    run_poll_trades,
    run_select_leaders,
    run_simulate,
)
from app.domain.models import LeaderTrade
from app.storage.db import get_connection, init_db
from app.storage.repositories import SignalRepository


def seed_snapshot(db_path: str):
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO portfolio_snapshots (
                captured_at, total_cost_basis, total_market_value,
                total_unrealized_pnl, total_realized_pnl, total_equity, drawdown_pct, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (datetime.now(timezone.utc).isoformat(), 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, '{"positions": []}'),
        )
        conn.commit()


def test_run_select_leaders_accepts_injected_client(tmp_path: Path, settings_factory):
    db_path = tmp_path / 'select.db'
    init_db(str(db_path))
    settings = settings_factory(str(db_path))

    class DummyClient:
        def fetch_leaders(self, **kwargs):
            return []

    result = run_select_leaders.run(settings, client=DummyClient())

    assert result['leaders_fetched'] == 0
    assert result['job_run_id'] is not None


def test_run_poll_trades_accepts_injected_client(tmp_path: Path, settings_factory):
    db_path = tmp_path / 'poll.db'
    init_db(str(db_path))
    settings = settings_factory(str(db_path))
    with get_connection(str(db_path)) as conn:
        conn.execute(
            "INSERT INTO leaders (rank, wallet, name, pseudonym, pnl_snapshot, volume_snapshot, selection_run_id, selected_at, raw_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, '0x1', 'alice', 'alice', None, None, 'run-1', datetime.now(timezone.utc).isoformat(), '{}'),
        )
        conn.commit()

    class DummyTradesClient:
        def fetch_recent_trades(self, **kwargs):
            return []

    result = run_poll_trades.run(settings, trades_client=DummyTradesClient())

    assert result['leaders_polled'] == 1
    assert result['leaders_fetched'] == 1
    assert result['trades_inserted'] == 0
    assert result['leader_errors'] == 0


def test_run_poll_trades_continues_when_one_leader_fetch_fails(tmp_path: Path, settings_factory):
    db_path = tmp_path / 'poll-partial-failure.db'
    init_db(str(db_path))
    settings = settings_factory(str(db_path))
    selected_at = datetime.now(timezone.utc).isoformat()
    with get_connection(str(db_path)) as conn:
        conn.executemany(
            """
            INSERT INTO leaders (
                rank, wallet, name, pseudonym, pnl_snapshot, volume_snapshot,
                selection_run_id, selected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, '0x1', 'alice', 'alice', None, None, 'run-1', selected_at, '{}'),
                (2, '0x2', 'bob', 'bob', None, None, 'run-1', selected_at, '{}'),
            ],
        )
        conn.commit()

    class PartiallyFailingTradesClient:
        def __init__(self):
            self.wallets_seen = []

        def fetch_recent_trades(self, **kwargs):
            wallet = kwargs['wallet']
            self.wallets_seen.append(wallet)
            if wallet == '0x1':
                raise PolymarketUpstreamError('leader fetch failed')
            return [
                LeaderTrade(
                    wallet=wallet,
                    leader_name=kwargs['leader_name'],
                    transaction_hash='0xtx-2',
                    condition_id='cond-2',
                    asset_id='asset-2',
                    side='BUY',
                    size=10.0,
                    price=0.42,
                    timestamp=datetime.now(timezone.utc),
                    market_title='Will Y happen?',
                    market_slug='will-y-happen',
                    raw_json={'tx': '0xtx-2'},
                )
            ]

    client = PartiallyFailingTradesClient()

    result = run_poll_trades.run(settings, trades_client=client)

    assert client.wallets_seen == ['0x1', '0x2']
    assert result['leaders_polled'] == 2
    assert result['leaders_fetched'] == 2
    assert result['trades_inserted'] == 1
    assert result['trades_skipped'] == 0
    assert result['leader_errors'] == 1
    assert result['leader_error_details'] == [
        {
            'wallet': '0x1',
            'leader_name': 'alice',
            'error': 'leader fetch failed',
        }
    ]

    with get_connection(str(db_path)) as conn:
        row = conn.execute(
            "SELECT wallet, leader_name, transaction_hash FROM leader_trades"
        ).fetchone()
        job_row = conn.execute(
            "SELECT status, error_message FROM job_runs WHERE id = ?",
            (result['job_run_id'],),
        ).fetchone()

    assert dict(row) == {'wallet': '0x2', 'leader_name': 'bob', 'transaction_hash': '0xtx-2'}
    assert dict(job_row) == {'status': 'completed', 'error_message': None}


def test_run_poll_trades_does_not_swallow_programming_errors(tmp_path: Path, settings_factory):
    db_path = tmp_path / 'poll-programming-error.db'
    init_db(str(db_path))
    settings = settings_factory(str(db_path))
    with get_connection(str(db_path)) as conn:
        conn.execute(
            "INSERT INTO leaders (rank, wallet, name, pseudonym, pnl_snapshot, volume_snapshot, selection_run_id, selected_at, raw_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, '0x1', 'alice', 'alice', None, None, 'run-1', datetime.now(timezone.utc).isoformat(), '{}'),
        )
        conn.commit()

    class BuggyTradesClient:
        def fetch_recent_trades(self, **kwargs):
            raise TypeError('client integration bug')

    with pytest.raises(TypeError, match='client integration bug'):
        run_poll_trades.run(settings, trades_client=BuggyTradesClient())


def test_run_generate_signals_accepts_injected_services(tmp_path: Path, settings_factory):
    db_path = tmp_path / 'signals.db'
    init_db(str(db_path))
    settings = settings_factory(str(db_path))

    class DummyMarketService:
        def __init__(self, conn, settings=None):
            self.conn = conn

    class DummySignalService:
        def __init__(self, conn, settings, market_service):
            self.conn = conn
        def run(self):
            return type('Result', (), {'processed_count': 2, 'accepted_count': 1, 'rejected_count': 1, 'inserted_count': 2, 'skipped_count': 0})()

    result = run_generate_signals.run(settings, market_service_cls=DummyMarketService, signal_service_cls=DummySignalService)

    assert result['processed'] == 2
    assert result['accepted'] == 1


def test_run_simulate_accepts_injected_services(tmp_path: Path, settings_factory):
    db_path = tmp_path / 'simulate.db'
    init_db(str(db_path))
    settings = settings_factory(str(db_path))

    class DummyMarketService:
        def __init__(self, conn, settings=None):
            self.conn = conn

    class DummySimulationService:
        def __init__(self, conn, settings, market_service):
            self.conn = conn
        def run(self):
            return type('Result', (), {'processed_count': 3, 'filled_count': 1, 'rejected_count': 2, 'inserted_orders': 3})()

    result = run_simulate.run(settings, market_service_cls=DummyMarketService, simulation_service_cls=DummySimulationService)

    assert result['filled'] == 1
    assert result['inserted_orders'] == 3


def test_run_simulate_skips_work_in_alert_only_mode(tmp_path: Path, settings_factory):
    db_path = tmp_path / 'simulate-alert-only.db'
    init_db(str(db_path))
    settings = settings_factory(str(db_path), scarf_execution_mode='alert_only')

    with get_connection(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO leader_trades (
                wallet, leader_name, transaction_hash, condition_id, asset_id, side,
                size, price, timestamp, market_title, market_slug, raw_json, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                '0x1', 'alice', '0xtx', 'cond1', 'asset_yes', 'BUY',
                10.0, 0.57, datetime.now(timezone.utc).isoformat(),
                'Will X happen?', 'will-x-happen', '{}', datetime.now(timezone.utc).isoformat(),
            ),
        )
        trade_id = conn.execute('SELECT id FROM leader_trades ORDER BY id DESC LIMIT 1').fetchone()[0]
        conn.execute(
            """
            INSERT INTO signals (
                leader_trade_id, wallet, leader_name, condition_id, asset_id, market_slug,
                side, leader_price, decision, reason, detected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade_id, '0x1', 'alice', 'cond1', 'asset_yes', 'will-x-happen',
                'BUY', 0.57, 'accepted', 'accepted', datetime.now(timezone.utc).isoformat(), '{}',
            ),
        )
        conn.commit()
        assert len(SignalRepository(conn).list_pending_accepted()) == 1

    class DummyMarketService:
        def __init__(self, conn, settings=None):
            raise AssertionError('market service should not be constructed in alert_only mode')

    class DummySimulationService:
        def __init__(self, conn, settings, market_service):
            raise AssertionError('simulation service should not be constructed in alert_only mode')

    result = run_simulate.run(settings, market_service_cls=DummyMarketService, simulation_service_cls=DummySimulationService)

    assert result['processed'] == 1
    assert result['filled'] == 0
    assert result['rejected'] == 0
    assert result['inserted_orders'] == 1
    assert result['suppressed'] == 1

    with get_connection(str(db_path)) as conn:
        assert len(SignalRepository(conn).list_pending_accepted()) == 0
        row = conn.execute('SELECT status, reason FROM sim_orders').fetchone()
        assert dict(row) == {'status': 'suppressed', 'reason': 'execution_mode_alert_only'}


def test_run_poll_trades_excludes_wallets_with_whitespace_without_changing_polled_semantics(tmp_path: Path, settings_factory):
    db_path = tmp_path / 'poll-excluded-whitespace.db'
    init_db(str(db_path))
    settings = settings_factory(str(db_path), scarf_excluded_wallets=(' 0x1 ',))
    selected_at = datetime.now(timezone.utc).isoformat()
    with get_connection(str(db_path)) as conn:
        conn.executemany(
            """
            INSERT INTO leaders (
                rank, wallet, name, pseudonym, pnl_snapshot, volume_snapshot,
                selection_run_id, selected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, '0x1', 'alice', 'alice', None, None, 'run-1', selected_at, '{}'),
                (2, '0x2', 'bob', 'bob', None, None, 'run-1', selected_at, '{}'),
            ],
        )
        conn.commit()

    class DummyTradesClient:
        def __init__(self):
            self.wallets_seen = []

        def fetch_recent_trades(self, **kwargs):
            self.wallets_seen.append(kwargs['wallet'])
            return []

    client = DummyTradesClient()
    result = run_poll_trades.run(settings, trades_client=client)

    assert client.wallets_seen == ['0x2']
    assert result['leaders_polled'] == 2
    assert result['leaders_fetched'] == 1
    assert result['leaders_excluded'] == 1


def test_run_mark_to_market_accepts_injected_services(tmp_path: Path, settings_factory):
    db_path = tmp_path / 'mtm.db'
    init_db(str(db_path))
    settings = settings_factory(str(db_path))

    class DummyMarketService:
        def __init__(self, conn, settings=None):
            self.conn = conn

    class DummyValuationService:
        def __init__(self, conn, settings, market_service):
            self.conn = conn
        def mark_to_market(self):
            return type('Result', (), {'positions_marked': 4, 'snapshot_id': 9})()

    result = run_mark_to_market.run(settings, market_service_cls=DummyMarketService, valuation_service_cls=DummyValuationService)

    assert result['positions_marked'] == 4
    assert result['snapshot_id'] == 9


def test_run_daily_report_accepts_injected_reporting_service(tmp_path: Path, settings_factory):
    db_path = tmp_path / 'daily.db'
    init_db(str(db_path))
    settings = settings_factory(str(db_path))

    class DummyReportingService:
        def __init__(self, conn, settings):
            self.conn = conn
        def generate_daily_report(self):
            return {'snapshot_id': 1, 'total_equity': 123.0}

    result = run_daily_report.run(settings, reporting_service_cls=DummyReportingService, artifact_writer=lambda report, project_root=None: {'report_json_path': 'x.json'})

    assert result['snapshot_id'] == 1
    assert result['report_json_path'] == 'x.json'


def test_run_final_report_accepts_injected_reporting_service(tmp_path: Path, settings_factory):
    db_path = tmp_path / 'final.db'
    init_db(str(db_path))
    settings = settings_factory(str(db_path))
    seed_snapshot(str(db_path))

    class DummyReportingService:
        def __init__(self, conn, settings):
            self.conn = conn
        def generate_final_report(self):
            return {'days_tracked': 60, 'max_drawdown_pct': 1.5}

    result = run_final_report.run(settings, reporting_service_cls=DummyReportingService, artifact_writer=lambda report, project_root=None: {'report_markdown_path': 'y.md'})

    assert result['days_tracked'] == 60
    assert result['report_markdown_path'] == 'y.md'
