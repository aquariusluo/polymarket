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
            INSERT INTO signals (
                leader_trade_id, wallet, leader_name, condition_id, asset_id,
                market_slug, side, leader_price, decision, reason, detected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (_insert_trade(conn, tx_hash='0xtx3', condition_id='cond1', asset_id='asset_yes'), '0x1', 'alice', 'cond1', 'asset_yes', 'slug', 'BUY', 0.55, 'rejected', 'wallet_excluded', datetime.now(timezone.utc).isoformat(), '{}'),
        )
        conn.execute(
            """
            INSERT INTO sim_orders (
                signal_id, condition_id, asset_id, market_slug, side, requested_notional,
                filled_notional, filled_shares, fill_price, leader_price, slippage_pct,
                status, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (2, 'cond1', 'asset_yes', 'slug', 'BUY', 100.0, 0.0, 0.0, None, 0.55, None, 'suppressed', 'execution_mode_alert_only', datetime.now(timezone.utc).isoformat()),
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
        assert daily['signal_rejection_reasons'] == {'wallet_excluded': 1}
        assert daily['execution_rejection_reasons'] == {}
        assert daily['execution_suppression_reasons'] == {'execution_mode_alert_only': 1}


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
            INSERT INTO signals (
                leader_trade_id, wallet, leader_name, condition_id, asset_id,
                market_slug, side, leader_price, decision, reason, detected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (_insert_trade(conn, tx_hash='0xtx4', condition_id='cond3', asset_id='asset_yes'), '0x1', 'alice', 'cond3', 'asset_yes', 'slug3', 'BUY', 0.55, 'accepted', 'accepted', datetime.now(timezone.utc).isoformat(), '{}'),
        )
        conn.execute(
            """
            INSERT INTO signals (
                leader_trade_id, wallet, leader_name, condition_id, asset_id,
                market_slug, side, leader_price, decision, reason, detected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (_insert_trade(conn, tx_hash='0xtx5', condition_id='cond4', asset_id='asset_yes'), '0x1', 'alice', 'cond4', 'asset_yes', 'slug4', 'BUY', 0.55, 'rejected', 'trade_timestamp_in_future', datetime.now(timezone.utc).isoformat(), '{}'),
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
        conn.execute(
            """
            INSERT INTO sim_orders (
                signal_id, condition_id, asset_id, market_slug, side, requested_notional,
                filled_notional, filled_shares, fill_price, leader_price, slippage_pct,
                status, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (3, 'cond3', 'asset_yes', 'slug3', 'BUY', 100.0, 0.0, 0.0, None, 0.55, None, 'suppressed', 'execution_mode_alert_only', datetime.now(timezone.utc).isoformat()),
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
        assert final['signal_rejection_reasons'] == {'trade_timestamp_in_future': 1}
        assert final['execution_rejection_reasons'] == {'book_unavailable': 1}
        assert final['execution_suppression_reasons'] == {'execution_mode_alert_only': 1}



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


def test_generate_shadow_evidence_report_surfaces_universe_and_coverage_gaps(tmp_path: Path):
    db_path = tmp_path / 'shadow-evidence.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        _insert_snapshot(conn, equity=100.0, drawdown_pct=0.0)
        rejected_reasons = [
            'market_unsupported',
            'market_unsupported',
            'too_close_to_expiry',
            'liquidity_below_threshold',
            'book_slippage_too_high',
            'market_unavailable',
        ]
        for idx, reason in enumerate(rejected_reasons, start=1):
            conn.execute(
                """
                INSERT INTO signals (
                    leader_trade_id, wallet, leader_name, condition_id, asset_id,
                    market_slug, side, leader_price, decision, reason, detected_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _insert_trade(conn, tx_hash=f'0xshadow-{idx}', condition_id=f'cond-{idx}', asset_id=f'asset-{idx}'),
                    '0x1',
                    'alice',
                    f'cond-{idx}',
                    f'asset-{idx}',
                    'slug',
                    'BUY',
                    0.55,
                    'rejected',
                    reason,
                    datetime.now(timezone.utc).isoformat(),
                    '{}',
                ),
            )
        conn.commit()

        report = ReportingService(conn, DummySettings()).generate_shadow_evidence_report()

        assert report['strategy_verdict'] == 'unclear'
        assert report['total_signal_count'] == 6
        assert report['rejected_signal_count'] == 6
        assert report['snapshot_coverage_count'] == 0
        assert report['sim_order_coverage_count'] == 0
        assert report['universe_quality_reasons'] == {
            'market_unsupported': 2,
            'too_close_to_expiry': 1,
            'liquidity_below_threshold': 1,
        }
        assert report['structural_copyability_proxy_reasons'] == {
            'book_slippage_too_high': 1,
            'market_unavailable': 1,
        }
        assert report['signal_evidence_counts'] == {
            'market_lookup': {'market_lookup': 2},
            'trade_filter': {'universe_quality': 2},
            'copyability': {'copyability': 2},
        }
        assert report['limitations']


def test_generate_shadow_evidence_report_can_be_promising_when_evidence_exists(tmp_path: Path):
    db_path = tmp_path / 'shadow-evidence-promising.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        _insert_snapshot(conn, equity=100.0, drawdown_pct=0.0)
        signal_ids = []
        for idx in range(1, 4):
            conn.execute(
                """
                INSERT INTO signals (
                    leader_trade_id, wallet, leader_name, condition_id, asset_id,
                    market_slug, side, leader_price, decision, reason, detected_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _insert_trade(conn, tx_hash=f'0xpromising-{idx}', condition_id=f'cond-p-{idx}', asset_id=f'asset-p-{idx}'),
                    '0x1',
                    'alice',
                    f'cond-p-{idx}',
                    f'asset-p-{idx}',
                    'slug',
                    'BUY',
                    0.55,
                    'accepted',
                    'accepted',
                    datetime.now(timezone.utc).isoformat(),
                    '{"copyability":{"asset_id":"asset-p","source":"live_book","reason":null}}',
                ),
            )
            signal_ids.append(conn.execute('SELECT last_insert_rowid()').fetchone()[0])
        for signal_id in signal_ids:
            conn.execute(
                """
                INSERT INTO sim_orders (
                    signal_id, condition_id, asset_id, market_slug, side, requested_notional,
                    filled_notional, filled_shares, fill_price, leader_price, slippage_pct,
                    status, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal_id, f'cond-for-{signal_id}', f'asset-for-{signal_id}', 'slug', 'BUY',
                    100.0, 100.0, 180.0, 0.56, 0.55, 1.81, 'filled', 'filled', datetime.now(timezone.utc).isoformat(),
                ),
            )
        conn.commit()

        report = ReportingService(conn, DummySettings()).generate_shadow_evidence_report()

        assert report['strategy_verdict'] == 'promising'
        assert report['snapshot_coverage_count'] == 3
        assert report['sim_order_coverage_count'] == 3
        assert report['signal_evidence_counts'] == {
            'copyability': {'accepted': 3},
        }
        assert report['limitations'] == []


def test_generate_shadow_evidence_report_prefers_signal_evidence_fields_when_present(tmp_path: Path):
    db_path = tmp_path / 'shadow-evidence-v2.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        _insert_snapshot(conn, equity=100.0, drawdown_pct=0.0)
        detected_at = datetime.now(timezone.utc).isoformat()
        rows = [
            ('0xv2-1', 'rejected', 'market_inactive_or_closed', '{"signal_evidence":{"stage":"trade_filter","category":"universe_quality","decision":"rejected","reason":"market_inactive_or_closed"}}'),
            ('0xv2-2', 'rejected', 'trade_too_old', '{"signal_evidence":{"stage":"trade_filter","category":"eligibility","decision":"rejected","reason":"trade_too_old"}}'),
            ('0xv2-3', 'accepted', 'accepted', '{"signal_evidence":{"stage":"copyability","category":"accepted","decision":"accepted","reason":null},"copyability":{"asset_id":"asset-v2","source":"live_book","reason":null}}'),
        ]
        for tx_hash, decision, reason, raw_json in rows:
            conn.execute(
                """
                INSERT INTO signals (
                    leader_trade_id, wallet, leader_name, condition_id, asset_id,
                    market_slug, side, leader_price, decision, reason, detected_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _insert_trade(conn, tx_hash=tx_hash, condition_id=f'cond-{tx_hash}', asset_id=f'asset-{tx_hash}'),
                    '0x1',
                    'alice',
                    f'cond-{tx_hash}',
                    f'asset-{tx_hash}',
                    'slug',
                    'BUY',
                    0.55,
                    decision,
                    reason,
                    detected_at,
                    raw_json,
                ),
            )
        conn.commit()

        report = ReportingService(conn, DummySettings()).generate_shadow_evidence_report()

        assert report['signal_evidence_counts'] == {
            'copyability': {'accepted': 1},
            'trade_filter': {'eligibility': 1, 'universe_quality': 1},
        }
        assert report['snapshot_coverage_count'] == 1


def test_generate_shadow_evidence_report_is_unclear_when_no_signals_exist(tmp_path: Path):
    db_path = tmp_path / 'shadow-evidence-empty.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        _insert_snapshot(conn, equity=100.0, drawdown_pct=0.0)
        conn.commit()

        report = ReportingService(conn, DummySettings()).generate_shadow_evidence_report()

        assert report['strategy_verdict'] == 'unclear'
        assert report['total_signal_count'] == 0
        assert report['rejected_signal_count'] == 0
        assert report['signal_evidence_counts'] == {}
        assert 'No signals are present in the current primary database yet.' in report['limitations']


def test_generate_shadow_evidence_report_stays_unclear_for_non_failure_rejections(tmp_path: Path):
    db_path = tmp_path / 'shadow-evidence-non-failure.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        _insert_snapshot(conn, equity=100.0, drawdown_pct=0.0)
        rows = [
            ('0xnf-1', 'wallet_excluded'),
            ('0xnf-2', 'trade_too_old'),
            ('0xnf-3', 'cooldown_duplicate_signal'),
        ]
        for tx_hash, reason in rows:
            conn.execute(
                """
                INSERT INTO signals (
                    leader_trade_id, wallet, leader_name, condition_id, asset_id,
                    market_slug, side, leader_price, decision, reason, detected_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _insert_trade(conn, tx_hash=tx_hash, condition_id=f'cond-{tx_hash}', asset_id=f'asset-{tx_hash}'),
                    '0x1',
                    'alice',
                    f'cond-{tx_hash}',
                    f'asset-{tx_hash}',
                    'slug',
                    'BUY',
                    0.55,
                    'rejected',
                    reason,
                    datetime.now(timezone.utc).isoformat(),
                    '{}',
                ),
            )
        conn.commit()

        report = ReportingService(conn, DummySettings()).generate_shadow_evidence_report()

        assert report['strategy_verdict'] == 'unclear'
        assert report['signal_evidence_counts'] == {
            'cooldown': {'cooldown': 1},
            'trade_filter': {'eligibility': 1},
            'wallet_filter': {'wallet_filter': 1},
        }


def test_generate_shadow_evidence_report_stays_unclear_without_any_fills(tmp_path: Path):
    db_path = tmp_path / 'shadow-evidence-no-fills.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        _insert_snapshot(conn, equity=100.0, drawdown_pct=0.0)
        signal_ids = []
        for idx in range(1, 3):
            conn.execute(
                """
                INSERT INTO signals (
                    leader_trade_id, wallet, leader_name, condition_id, asset_id,
                    market_slug, side, leader_price, decision, reason, detected_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _insert_trade(conn, tx_hash=f'0xnofill-{idx}', condition_id=f'cond-nf-{idx}', asset_id=f'asset-nf-{idx}'),
                    '0x1',
                    'alice',
                    f'cond-nf-{idx}',
                    f'asset-nf-{idx}',
                    'slug',
                    'BUY',
                    0.55,
                    'accepted',
                    'accepted',
                    datetime.now(timezone.utc).isoformat(),
                    '{"copyability":{"asset_id":"asset-nf","source":"live_book","reason":null}}',
                ),
            )
            signal_ids.append(conn.execute('SELECT last_insert_rowid()').fetchone()[0])
        for signal_id in signal_ids:
            conn.execute(
                """
                INSERT INTO sim_orders (
                    signal_id, condition_id, asset_id, market_slug, side, requested_notional,
                    filled_notional, filled_shares, fill_price, leader_price, slippage_pct,
                    status, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal_id, f'cond-for-{signal_id}', f'asset-for-{signal_id}', 'slug', 'BUY',
                    100.0, 0.0, 0.0, None, 0.55, None, 'rejected', 'book_unavailable', datetime.now(timezone.utc).isoformat(),
                ),
            )
        conn.commit()

        report = ReportingService(conn, DummySettings()).generate_shadow_evidence_report()

        assert report['strategy_verdict'] == 'unclear'
        assert 'Sim-order rows exist, but none have filled yet.' in report['limitations']
