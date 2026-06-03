from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.storage.db import get_connection, init_db


def _insert_gate_signal(conn, *, tx_hash: str, detected_at: str, status: str | None = None, reason: str | None = None, condition_id: str = 'cond-gate') -> None:
    conn.execute(
        """
        INSERT INTO leader_trades (
            wallet, leader_name, transaction_hash, condition_id, asset_id, side,
            size, price, timestamp, market_title, market_slug, raw_json, ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            '0xleader', 'alice', tx_hash, condition_id, f'asset-{tx_hash}', 'BUY',
            '1.000000', '0.500000', detected_at, 'Gate market', 'gate-market', '{}', detected_at,
        ),
    )
    trade_id = conn.execute('SELECT id FROM leader_trades WHERE transaction_hash = ?', (tx_hash,)).fetchone()[0]
    conn.execute(
        """
        INSERT INTO signals (
            leader_trade_id, wallet, leader_name, condition_id, asset_id, market_slug,
            side, leader_price, decision, reason, detected_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            trade_id, '0xleader', 'alice', condition_id, f'asset-{tx_hash}', 'gate-market',
            'BUY', '0.500000', 'accepted', 'accepted', detected_at, '{}',
        ),
    )
    if status is not None:
        signal_id = conn.execute('SELECT id FROM signals WHERE leader_trade_id = ?', (trade_id,)).fetchone()[0]
        conn.execute(
            """
            INSERT INTO sim_orders (
                signal_id, condition_id, asset_id, market_slug, side, requested_notional,
                filled_notional, filled_shares, fill_price, leader_price, slippage_pct,
                status, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal_id, condition_id, f'asset-{tx_hash}', 'gate-market', 'BUY',
                '10.00', '10.00' if status == 'filled' else '0.00',
                '20.000000' if status == 'filled' else '0.000000',
                '0.500000' if status == 'filled' else None,
                '0.500000', '0.0000' if status == 'filled' else None,
                status, reason, detected_at,
            ),
        )


def test_daily_report_job_writes_latest_summary_markdown_and_json(tmp_path: Path, settings_factory):
    from app.jobs import run_daily_report

    project_dir = tmp_path / 'project'
    report_dir = project_dir / '.scarf' / 'reports'
    report_dir.mkdir(parents=True)
    db_path = project_dir / 'data.db'
    init_db(str(db_path))
    settings = settings_factory(str(db_path))

    with get_connection(str(db_path)) as conn:
        detected_at = '2030-01-01T00:00:00+00:00'
        conn.execute(
            """
            INSERT INTO leader_trades (
                wallet, leader_name, transaction_hash, condition_id, asset_id, side,
                size, price, timestamp, market_title, market_slug, raw_json, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ('0x1', 'alice', '0xtx-report-1', 'cond1', 'asset_yes', 'BUY', 1.0, 0.5, detected_at, 'Market', 'slug', '{}', detected_at),
        )
        trade_id = conn.execute("SELECT id FROM leader_trades WHERE transaction_hash = '0xtx-report-1'").fetchone()[0]
        conn.execute(
            """
            INSERT INTO signals (
                leader_trade_id, wallet, leader_name, condition_id, asset_id,
                market_slug, side, leader_price, decision, reason, detected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (trade_id, '0x1', 'alice', 'cond1', 'asset_yes', 'slug', 'BUY', 0.5, 'rejected', 'wallet_excluded', detected_at, '{}'),
        )
        conn.execute(
            """
            INSERT INTO portfolio_snapshots (
                captured_at, total_cost_basis, total_market_value,
                total_unrealized_pnl, total_realized_pnl, total_equity, drawdown_pct, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ('2030-01-01T00:00:00+00:00', 100.0, 110.0, 10.0, 0.0, 110.0, 0.0, '{"positions": []}'),
        )
        conn.commit()

    result = run_daily_report.run(settings, project_root=str(project_dir))

    latest_md = report_dir / 'latest-summary.md'
    latest_json = report_dir / 'latest-summary.json'

    assert latest_md.exists()
    assert latest_json.exists()
    assert result['report_markdown_path'].endswith('latest-summary.md')
    assert result['report_json_path'].endswith('latest-summary.json')
    latest_text = latest_md.read_text(encoding='utf-8')
    assert 'Latest Trade Follow Summary' in latest_text
    assert 'Signal Reject Reasons: wallet_excluded=1' in latest_text
    assert 'Execution Rejections: none' in latest_text
    assert 'Execution Suppressions: none' in latest_text
    payload = json.loads(latest_json.read_text(encoding='utf-8'))
    assert payload['total_equity'] == 110.0


def test_final_report_job_writes_performance_review_markdown_and_json(tmp_path: Path, settings_factory):
    from app.jobs import run_final_report

    project_dir = tmp_path / 'project'
    report_dir = project_dir / '.scarf' / 'reports'
    report_dir.mkdir(parents=True)
    db_path = project_dir / 'data.db'
    init_db(str(db_path))
    settings = settings_factory(str(db_path))

    with get_connection(str(db_path)) as conn:
        detected_at = '2030-01-15T00:00:00+00:00'
        conn.execute(
            """
            INSERT INTO leader_trades (
                wallet, leader_name, transaction_hash, condition_id, asset_id, side,
                size, price, timestamp, market_title, market_slug, raw_json, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ('0x1', 'alice', '0xtx-review-1', 'cond1', 'asset_yes', 'BUY', 1.0, 0.5, detected_at, 'Market', 'slug', '{}', detected_at),
        )
        trade_id = conn.execute("SELECT id FROM leader_trades WHERE transaction_hash = '0xtx-review-1'").fetchone()[0]
        conn.execute(
            """
            INSERT INTO signals (
                leader_trade_id, wallet, leader_name, condition_id, asset_id,
                market_slug, side, leader_price, decision, reason, detected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (trade_id, '0x1', 'alice', 'cond1', 'asset_yes', 'slug', 'BUY', 0.5, 'accepted', 'accepted', detected_at, '{}'),
        )
        signal_id = conn.execute('SELECT id FROM signals WHERE leader_trade_id = ?', (trade_id,)).fetchone()[0]
        conn.execute(
            """
            INSERT INTO sim_orders (
                signal_id, condition_id, asset_id, market_slug, side, requested_notional,
                filled_notional, filled_shares, fill_price, leader_price, slippage_pct,
                status, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (signal_id, 'cond1', 'asset_yes', 'slug', 'BUY', '10.00', '0.00', '0.000000', None, '0.500000', None, 'suppressed', 'execution_mode_alert_only', detected_at),
        )
        conn.execute(
            """
            INSERT INTO portfolio_snapshots (
                captured_at, total_cost_basis, total_market_value,
                total_unrealized_pnl, total_realized_pnl, total_equity, drawdown_pct, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ('2030-01-01T00:00:00+00:00', 100.0, 100.0, 0.0, 0.0, 100.0, 0.0, '{"positions": []}'),
        )
        conn.execute(
            """
            INSERT INTO portfolio_snapshots (
                captured_at, total_cost_basis, total_market_value,
                total_unrealized_pnl, total_realized_pnl, total_equity, drawdown_pct, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ('2030-02-01T00:00:00+00:00', 100.0, 125.0, 25.0, 0.0, 125.0, 5.0, '{"positions": []}'),
        )
        conn.commit()

    result = run_final_report.run(settings, project_root=str(project_dir))

    review_md = report_dir / 'performance-review.md'
    review_json = report_dir / 'performance-review.json'

    assert review_md.exists()
    assert review_json.exists()
    assert result['report_markdown_path'].endswith('performance-review.md')
    assert result['report_json_path'].endswith('performance-review.json')
    review_text = review_md.read_text(encoding='utf-8')
    assert '60-Day Review Notes' in review_text
    assert 'Signal Reject Reasons: none' in review_text
    assert 'Execution Rejections: none' in review_text
    assert 'Execution Suppressions: execution_mode_alert_only=1' in review_text
    payload = json.loads(review_json.read_text(encoding='utf-8'))
    assert payload['ending_equity'] == 125.0


def test_run_pipeline_writes_detection_log_and_shadow_run_artifact(tmp_path: Path, settings_factory):
    from app.jobs import run_pipeline

    project_dir = tmp_path / 'project'
    report_dir = project_dir / '.scarf' / 'reports'
    report_dir.mkdir(parents=True)
    db_path = project_dir / 'data.db'
    init_db(str(db_path))
    settings = settings_factory(str(db_path))

    def noop(name: str):
        return lambda settings=None, **kwargs: {'step': name, 'ok': True}

    result = run_pipeline.run(
        settings,
        steps={
            'select-leaders': noop('select-leaders'),
            'poll-trades': noop('poll-trades'),
            'generate-signals': noop('generate-signals'),
            'simulate': noop('simulate'),
            'mark-to-market': noop('mark-to-market'),
            'daily-report': noop('daily-report'),
        },
        project_root=str(project_dir),
    )

    detection_log = report_dir / 'detection.log'
    shadow_json = report_dir / 'shadow-run-latest.json'

    assert detection_log.exists()
    assert shadow_json.exists()
    assert result['shadow_run_path'].endswith('shadow-run-latest.json')
    log_line = detection_log.read_text(encoding='utf-8').strip().splitlines()[-1]
    assert 'run-loop' in log_line
    payload = json.loads(shadow_json.read_text(encoding='utf-8'))
    assert payload['completed'] is True
    assert payload['iteration_count'] == 1


def test_gate_report_writes_hold_decision_when_no_fills(tmp_path: Path, settings_factory):
    from app.jobs import run_gate_report

    project_dir = tmp_path / 'project'
    report_dir = project_dir / '.scarf' / 'reports'
    report_dir.mkdir(parents=True)
    db_path = project_dir / 'data.db'
    init_db(str(db_path))
    settings = settings_factory(str(db_path))
    now = datetime.now(timezone.utc).isoformat()

    with get_connection(str(db_path)) as conn:
        _insert_gate_signal(conn, tx_hash='hold-1', detected_at=now, status='rejected', reason='slippage_too_high')
        conn.commit()

    result = run_gate_report.run(settings, project_root=str(project_dir))

    gate_md = report_dir / 'auto-follow-gate.md'
    gate_json = report_dir / 'auto-follow-gate.json'
    assert gate_md.exists()
    assert gate_json.exists()
    assert result['status'] == 'hold'
    assert result['decision'] == 'manual_confirm_only'
    payload = json.loads(gate_json.read_text(encoding='utf-8'))
    assert payload['filled_orders_window'] == 0
    assert payload['slippage_reject_ratio'] == 1.0
    assert 'Only 0 fills in 72h window' in gate_md.read_text(encoding='utf-8')


def test_gate_report_passes_when_recent_fills_meet_thresholds(tmp_path: Path, settings_factory):
    from app.jobs import run_gate_report

    project_dir = tmp_path / 'project'
    report_dir = project_dir / '.scarf' / 'reports'
    report_dir.mkdir(parents=True)
    db_path = project_dir / 'data.db'
    init_db(str(db_path))
    settings = settings_factory(str(db_path))
    now = datetime.now(timezone.utc).isoformat()

    with get_connection(str(db_path)) as conn:
        for idx in range(10):
            _insert_gate_signal(conn, tx_hash=f'pass-{idx}', detected_at=now, status='filled', reason='filled', condition_id=f'cond-gate-{idx}')
        conn.commit()

    result = run_gate_report.run(settings, project_root=str(project_dir))

    assert result['status'] == 'pass'
    assert result['decision'] == 'auto_follow_candidate'
    payload = json.loads((report_dir / 'auto-follow-gate.json').read_text(encoding='utf-8'))
    assert payload['filled_orders_window'] == 10
    assert payload['notes'] == ['All gate conditions met in current window.']


def test_shadow_evidence_job_writes_markdown_and_json(tmp_path: Path, settings_factory):
    from app.jobs import run_shadow_evidence

    project_dir = tmp_path / 'project'
    report_dir = project_dir / '.scarf' / 'reports'
    report_dir.mkdir(parents=True)
    db_path = project_dir / 'data.db'
    init_db(str(db_path))
    settings = settings_factory(str(db_path))

    with get_connection(str(db_path)) as conn:
        detected_at = '2030-01-01T00:00:00+00:00'
        conn.execute(
            """
            INSERT INTO leader_trades (
                wallet, leader_name, transaction_hash, condition_id, asset_id, side,
                size, price, timestamp, market_title, market_slug, raw_json, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ('0x1', 'alice', '0xtx-shadow-1', 'cond1', 'asset_yes', 'BUY', 1.0, 0.5, detected_at, 'Market', 'slug', '{}', detected_at),
        )
        trade_id = conn.execute("SELECT id FROM leader_trades WHERE transaction_hash = '0xtx-shadow-1'").fetchone()[0]
        conn.execute(
            """
            INSERT INTO signals (
                leader_trade_id, wallet, leader_name, condition_id, asset_id,
                market_slug, side, leader_price, decision, reason, detected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade_id,
                '0x1',
                'alice',
                'cond1',
                'asset_yes',
                'slug',
                'BUY',
                0.5,
                'rejected',
                'market_unsupported',
                detected_at,
                '{"signal_evidence":{"stage":"market_lookup","category":"market_lookup","decision":"rejected","reason":"market_unsupported"}}',
            ),
        )
        conn.execute(
            """
            INSERT INTO portfolio_snapshots (
                captured_at, total_cost_basis, total_market_value,
                total_unrealized_pnl, total_realized_pnl, total_equity, drawdown_pct, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (detected_at, 100.0, 100.0, 0.0, 0.0, 100.0, 0.0, '{"positions": []}'),
        )
        conn.commit()

    result = run_shadow_evidence.run(settings, project_root=str(project_dir))

    shadow_md = report_dir / 'shadow-evidence.md'
    shadow_json = report_dir / 'shadow-evidence.json'

    assert shadow_md.exists()
    assert shadow_json.exists()
    assert result['report_markdown_path'].endswith('shadow-evidence.md')
    assert result['report_json_path'].endswith('shadow-evidence.json')
    shadow_text = shadow_md.read_text(encoding='utf-8')
    assert 'Shadow Evidence Report' in shadow_text
    assert 'Strategy Verdict: failing' in shadow_text
    assert 'Universe Quality Reasons: market_unsupported=1' in shadow_text
    assert 'Signal Evidence Counts: market_lookup(market_lookup=1)' in shadow_text
    payload = json.loads(shadow_json.read_text(encoding='utf-8'))
    assert payload['strategy_verdict'] == 'failing'
    assert payload['signal_evidence_counts'] == {'market_lookup': {'market_lookup': 1}}
