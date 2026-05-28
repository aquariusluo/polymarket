from __future__ import annotations

import json
from pathlib import Path

from app.config import get_settings


def write_manifest(project_root: Path) -> None:
    scarf_dir = project_root / '.scarf'
    scarf_dir.mkdir(parents=True, exist_ok=True)
    (scarf_dir / 'manifest.json').write_text(
        json.dumps(
            {
                'schemaVersion': 2,
                'id': 'aquariusluo/polymarket-leader-follower',
                'name': 'Polymarket Leader Follower',
                'version': '1.0.0',
                'description': 'Track copy-trading performance.',
                'contents': {'dashboard': True, 'agentsMd': True, 'config': 12},
                'config': {
                    'schema': [
                        {'key': 'leaderboard_source', 'type': 'string', 'default': 'Polymarket profit leaderboard'},
                        {'key': 'leader_selection_mode', 'type': 'enum', 'default': 'fixed_override', 'options': [{'label': 'Live', 'value': 'live_top5'}, {'label': 'Fixed', 'value': 'fixed_override'}]},
                        {'key': 'top_accounts_override', 'type': 'list', 'itemType': 'string', 'default': ['0xA', '0xB', '0xC']},
                        {'key': 'execution_mode', 'type': 'enum', 'default': 'alert_only', 'options': [{'label': 'Alert', 'value': 'alert_only'}, {'label': 'Manual', 'value': 'manual_confirm'}]},
                        {'key': 'bankroll_usd', 'type': 'number', 'default': 4321},
                        {'key': 'max_copy_usd_per_order', 'type': 'number', 'default': 77},
                        {'key': 'max_daily_orders', 'type': 'number', 'default': 9},
                        {'key': 'slippage_bps', 'type': 'number', 'default': 125},
                        {'key': 'evaluation_start_date', 'type': 'string', 'default': '2026-05-24'},
                        {'key': 'evaluation_days', 'type': 'number', 'default': 60},
                        {'key': 'excluded_wallets', 'type': 'list', 'itemType': 'string', 'default': ['0xBAD']},
                        {'key': 'operator_notes', 'type': 'text', 'default': 'Stay conservative'},
                    ]
                },
            }
        ),
        encoding='utf-8',
    )


def test_get_settings_reads_manifest_defaults_when_env_missing(tmp_path: Path, monkeypatch):
    project_root = tmp_path / 'project'
    write_manifest(project_root)
    monkeypatch.chdir(project_root)
    for key in [
        'TOP_N', 'FIXED_TRADE_USDC', 'MAX_SLIPPAGE_PCT', 'RUN_LOOP_MAX_ITERATIONS',
        'LEADERBOARD_CATEGORY', 'LEADERBOARD_TIME', 'LEADERBOARD_SORT',
    ]:
        monkeypatch.delenv(key, raising=False)

    settings = get_settings()

    assert settings.top_n == 3
    assert settings.fixed_trade_usdc == 77.0
    assert settings.max_slippage_pct == 1.25
    assert settings.run_loop_max_iterations == 1
    assert settings.scarf_execution_mode == 'alert_only'
    assert settings.scarf_bankroll_usd == 4321.0
    assert settings.scarf_evaluation_days == 60
    assert settings.scarf_top_accounts_override == ('0xA', '0xB', '0xC')


def test_shadow_run_updates_dashboard_and_cron_jobs(tmp_path: Path):
    from app.jobs import run_shadow

    project_root = tmp_path / 'project'
    write_manifest(project_root)
    scarf_dir = project_root / '.scarf'
    dashboard = {
        'version': 1,
        'title': 'Polymarket Leader Follower',
        'description': 'Track copy-trading performance.',
        'updatedAt': '2026-01-01T00:00:00Z',
        'sections': [
            {
                'title': 'Current Status',
                'columns': 4,
                'widgets': [
                    {'type': 'stat', 'title': 'Execution Mode', 'value': 'manual_confirm', 'color': 'blue'},
                    {'type': 'stat', 'title': 'Tracked Leaders', 'value': 5, 'color': 'purple'},
                    {'type': 'stat', 'title': 'Copy Bankroll (USD)', 'value': 'Set in config', 'color': 'green'},
                    {'type': 'stat', 'title': '60-Day PnL', 'value': 'Pending', 'color': 'gray'},
                ],
            },
            {
                'title': 'Leader Watchlist',
                'columns': 1,
                'widgets': [
                    {'type': 'table', 'title': 'Top 5 Source Accounts', 'columns': ['Rank', 'Wallet / Alias', 'Last Seen', 'Status'], 'rows': []}
                ],
            },
            {
                'title': 'Performance Review',
                'columns': 1,
                'widgets': [
                    {'type': 'chart', 'title': 'Cumulative Copy PnL', 'chartType': 'line', 'series': [{'name': 'PnL', 'color': 'green', 'data': []}]}
                ],
            },
        ],
    }
    scarf_dir.mkdir(parents=True, exist_ok=True)
    (scarf_dir / 'dashboard.json').write_text(json.dumps(dashboard), encoding='utf-8')

    def _daily_report_step(_settings, **_kwargs):
        return {
            'captured_at': '2030-01-01T00:00:00+00:00',
            'snapshot_count': 1,
            'total_equity': 0.0,
            'accepted_signal_count': 0,
            'filled_order_count': 0,
            'rejected_order_count': 0,
        }

    def _ok_step(_settings, **_kwargs):
        return {}

    result = run_shadow.run(
        project_root=str(project_root),
        steps={
            'select-leaders': _ok_step,
            'poll-trades': _ok_step,
            'generate-signals': _ok_step,
            'simulate': _ok_step,
            'mark-to-market': _ok_step,
            'daily-report': _daily_report_step,
        },
    )

    dashboard_after = json.loads((scarf_dir / 'dashboard.json').read_text(encoding='utf-8'))
    current_stats = {w['title']: w for w in dashboard_after['sections'][0]['widgets']}
    assert current_stats['Execution Mode']['value'] == 'alert_only'
    assert current_stats['Tracked Leaders']['value'] == 3
    assert current_stats['Copy Bankroll (USD)']['value'] == 4321
    assert current_stats['60-Day PnL']['value'] == '0.00 USD'

    watch_rows = dashboard_after['sections'][1]['widgets'][0]['rows']
    assert len(watch_rows) == 3
    assert watch_rows[0][1] == '0xA'

    chart_data = dashboard_after['sections'][2]['widgets'][0]['series'][0]['data']
    assert chart_data[-1]['y'] == 0.0

    cron_jobs = json.loads((project_root / 'cron' / 'jobs.json').read_text(encoding='utf-8'))
    assert len(cron_jobs) == 2
    assert '{{PROJECT_DIR}}' in cron_jobs[0]['prompt']
    assert result['dashboard_path'].endswith('.scarf/dashboard.json')
    assert result['cron_jobs_path'].endswith('cron/jobs.json')



def test_update_dashboard_uses_live_leaders_and_signal_order_stats(tmp_path: Path):
    import json

    from app.config import Settings
    from app.domain.models import Leader
    from app.services.scarf_service import update_dashboard
    from app.storage.db import get_connection, init_db
    from app.storage.repositories import LeaderRepository

    project_root = tmp_path / 'project'
    scarf_dir = project_root / '.scarf'
    scarf_dir.mkdir(parents=True, exist_ok=True)
    db_path = project_root / 'data.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        LeaderRepository(conn).insert_many(
            [
                Leader(rank=1, wallet='0xL1', name='Leader One', pseudonym='L1', pnl_snapshot=100.0, volume_snapshot=1000.0, raw_json={}),
                Leader(rank=2, wallet='0xL2', name='Leader Two', pseudonym='L2', pnl_snapshot=90.0, volume_snapshot=900.0, raw_json={}),
            ],
            selection_run_id='run-live-1',
        )

    dashboard = {
        'version': 1,
        'title': 'Polymarket Leader Follower',
        'description': 'Track copy-trading performance.',
        'updatedAt': '2026-01-01T00:00:00Z',
        'sections': [
            {
                'title': 'Current Status',
                'columns': 4,
                'widgets': [
                    {'type': 'stat', 'title': 'Execution Mode', 'value': 'manual_confirm', 'color': 'blue'},
                    {'type': 'stat', 'title': 'Tracked Leaders', 'value': 0, 'color': 'purple'},
                    {'type': 'stat', 'title': 'Copy Bankroll (USD)', 'value': 0, 'color': 'green'},
                    {'type': 'stat', 'title': '60-Day PnL', 'value': 'Pending', 'color': 'gray'},
                    {'type': 'stat', 'title': 'Accepted Signals', 'value': 0, 'color': 'blue'},
                    {'type': 'stat', 'title': 'Filled Orders', 'value': 0, 'color': 'green'},
                    {'type': 'stat', 'title': 'Rejected Orders', 'value': 0, 'color': 'red'},
                ],
            },
            {
                'title': 'Leader Watchlist',
                'columns': 1,
                'widgets': [
                    {'type': 'table', 'title': 'Top 5 Source Accounts', 'columns': ['Rank', 'Wallet / Alias', 'Last Seen', 'Status'], 'rows': []}
                ],
            },
            {
                'title': 'Performance Review',
                'columns': 1,
                'widgets': [
                    {'type': 'chart', 'title': 'Cumulative Copy PnL', 'chartType': 'line', 'series': [{'name': 'PnL', 'color': 'green', 'data': []}]}
                ],
            },
        ],
    }
    (scarf_dir / 'dashboard.json').write_text(json.dumps(dashboard), encoding='utf-8')

    settings = Settings(
        app_env='test',
        db_path=str(db_path),
        leaderboard_category='overall',
        leaderboard_time='30d',
        leaderboard_sort='profit',
        top_n=5,
        poll_interval_seconds=0,
        trade_fetch_limit=50,
        min_time_to_expiry_hours=24,
        min_market_liquidity=10000.0,
        signal_cooldown_minutes=5,
        fixed_trade_usdc=77.0,
        per_market_cap_usdc=300.0,
        max_slippage_pct=1.25,
        market_cache_ttl_seconds=300,
        run_loop_max_iterations=1,
        run_loop_sleep_seconds=0,
        scarf_execution_mode='manual_confirm',
        scarf_bankroll_usd=4321.0,
        scarf_evaluation_days=60,
        scarf_top_accounts_override=[],
        scarf_excluded_wallets=[],
        scarf_operator_notes='',
        scarf_leader_selection_mode='live_top5',
        scarf_leaderboard_source='Polymarket profit leaderboard',
        scarf_evaluation_start_date='2026-05-24',
    )

    pipeline_result = {
        'iterations': [
            {
                'iteration': 1,
                'completed': True,
                'failed_step': None,
                'steps': [
                    {'name': 'daily-report', 'status': 'ok', 'result': {
                        'captured_at': '2030-01-01T00:00:00+00:00',
                        'snapshot_count': 4,
                        'total_equity': 12.5,
                        'accepted_signal_count': 7,
                        'filled_order_count': 3,
                        'rejected_order_count': 2,
                    }},
                ],
            }
        ]
    }

    update_dashboard(project_root=str(project_root), settings=settings, pipeline_result=pipeline_result)

    dashboard_after = json.loads((scarf_dir / 'dashboard.json').read_text(encoding='utf-8'))
    current_stats = {w['title']: w for w in dashboard_after['sections'][0]['widgets']}
    assert current_stats['Tracked Leaders']['value'] == 2
    assert current_stats['Accepted Signals']['value'] == 7
    assert current_stats['Filled Orders']['value'] == 3
    assert current_stats['Rejected Orders']['value'] == 2

    watch_rows = dashboard_after['sections'][1]['widgets'][0]['rows']
    assert watch_rows[0] == ['1', '0xL1', '2030-01-01T00:00:00+00:00', 'active']
    assert watch_rows[1] == ['2', '0xL2', '2030-01-01T00:00:00+00:00', 'active']



def test_update_dashboard_syncs_ops_widgets_and_60_day_verdict(tmp_path: Path):
    import json

    from app.config import Settings
    from app.services.scarf_service import update_dashboard
    from app.storage.db import get_connection, init_db
    from app.storage.repositories import JobRunRepository

    project_root = tmp_path / 'project'
    scarf_dir = project_root / '.scarf'
    scarf_dir.mkdir(parents=True, exist_ok=True)
    db_path = project_root / 'data.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        repo = JobRunRepository(conn)
        first = repo.start('select-leaders')
        repo.finish(first, status='completed', inserted_count=5, skipped_count=0)
        second = repo.start('poll-trades')
        repo.finish(second, status='completed', inserted_count=4, skipped_count=9)
        third = repo.start('generate-signals')
        repo.finish(third, status='failed', inserted_count=1, skipped_count=2, error_message='cooldown duplicate')

    dashboard = {
        'version': 1,
        'title': 'Polymarket Leader Follower',
        'description': 'Track copy-trading performance.',
        'updatedAt': '2026-01-01T00:00:00Z',
        'sections': [
            {
                'title': 'Current Status',
                'columns': 4,
                'widgets': [
                    {'type': 'stat', 'title': 'Execution Mode', 'value': 'manual_confirm', 'color': 'blue'},
                    {'type': 'stat', 'title': 'Tracked Leaders', 'value': 0, 'color': 'purple'},
                    {'type': 'stat', 'title': 'Copy Bankroll (USD)', 'value': 0, 'color': 'green'},
                    {'type': 'stat', 'title': '60-Day PnL', 'value': 'Pending', 'color': 'gray'},
                    {'type': 'stat', 'title': 'Accepted Signals', 'value': 0, 'color': 'blue'},
                    {'type': 'stat', 'title': 'Filled Orders', 'value': 0, 'color': 'green'},
                    {'type': 'stat', 'title': 'Rejected Orders', 'value': 0, 'color': 'red'},
                ],
            },
            {
                'title': 'Ops Health',
                'columns': 3,
                'widgets': [
                    {'type': 'stat', 'title': 'Shadow Run Status', 'value': 'unknown', 'color': 'gray'},
                    {'type': 'stat', 'title': 'Pipeline Iterations', 'value': 0, 'color': 'blue'},
                    {'type': 'stat', 'title': 'Trades Inserted', 'value': 0, 'color': 'green'},
                    {'type': 'stat', 'title': 'Trades Skipped', 'value': 0, 'color': 'yellow'},
                    {'type': 'stat', 'title': 'Signals Processed', 'value': 0, 'color': 'purple'},
                    {'type': 'stat', 'title': '60-Day Verdict', 'value': 'Pending', 'color': 'gray'},
                    {'type': 'table', 'title': 'Recent Job Runs', 'columns': ['Job', 'Status', 'Inserted', 'Skipped', 'Error'], 'rows': []},
                ],
            },
        ],
    }
    (scarf_dir / 'dashboard.json').write_text(json.dumps(dashboard), encoding='utf-8')

    settings = Settings(
        app_env='test',
        db_path=str(db_path),
        leaderboard_category='overall',
        leaderboard_time='30d',
        leaderboard_sort='profit',
        top_n=5,
        poll_interval_seconds=0,
        trade_fetch_limit=50,
        min_time_to_expiry_hours=24,
        min_market_liquidity=10000.0,
        signal_cooldown_minutes=5,
        fixed_trade_usdc=77.0,
        per_market_cap_usdc=300.0,
        max_slippage_pct=1.25,
        market_cache_ttl_seconds=300,
        run_loop_max_iterations=1,
        run_loop_sleep_seconds=0,
        scarf_execution_mode='manual_confirm',
        scarf_bankroll_usd=4321.0,
        scarf_evaluation_days=60,
        scarf_top_accounts_override=['0xA'],
        scarf_excluded_wallets=[],
        scarf_operator_notes='',
        scarf_leader_selection_mode='fixed_override',
        scarf_leaderboard_source='Polymarket profit leaderboard',
        scarf_evaluation_start_date='2024-01-01',
    )

    pipeline_result = {
        'iteration_count': 2,
        'completed': True,
        'failed_step': None,
        'iterations': [
            {
                'iteration': 2,
                'completed': True,
                'failed_step': None,
                'steps': [
                    {'name': 'poll-trades', 'status': 'ok', 'result': {'trades_inserted': 4, 'trades_skipped': 9}},
                    {'name': 'generate-signals', 'status': 'ok', 'result': {'processed': 6, 'accepted': 2, 'rejected': 4, 'inserted': 6}},
                    {'name': 'daily-report', 'status': 'ok', 'result': {
                        'captured_at': '2030-01-01T00:00:00+00:00',
                        'snapshot_count': 4,
                        'total_equity': 15.5,
                        'accepted_signal_count': 2,
                        'filled_order_count': 1,
                        'rejected_order_count': 3,
                    }},
                ],
            }
        ]
    }

    update_dashboard(project_root=str(project_root), settings=settings, pipeline_result=pipeline_result)

    dashboard_after = json.loads((scarf_dir / 'dashboard.json').read_text(encoding='utf-8'))
    widgets = {}
    for section in dashboard_after['sections']:
        for widget in section['widgets']:
            widgets[widget['title']] = widget

    assert widgets['Shadow Run Status']['value'] == 'completed'
    assert widgets['Pipeline Iterations']['value'] == 2
    assert widgets['Trades Inserted']['value'] == 4
    assert widgets['Trades Skipped']['value'] == 9
    assert widgets['Signals Processed']['value'] == 6
    assert widgets['60-Day Verdict']['value'] == 'matured_profitable'

    job_rows = widgets['Recent Job Runs']['rows']
    assert job_rows[0][:4] == ['generate-signals', 'failed', '1', '2']
    assert job_rows[0][4] == 'cooldown duplicate'
    assert job_rows[1][:4] == ['poll-trades', 'completed', '4', '9']



def test_scarf_service_wrappers_delegate_to_split_modules(monkeypatch):
    from app.services import scarf_service

    calls = []

    def fake_update_dashboard(*, project_root=None, settings=None, pipeline_result=None):
        calls.append(('dashboard', project_root, settings, pipeline_result))
        return '/tmp/dashboard.json'

    def fake_write_default_cron_jobs(project_root=None):
        calls.append(('cron', project_root))
        return '/tmp/jobs.json'

    monkeypatch.setattr('app.services.dashboard_service.update_dashboard', fake_update_dashboard)
    monkeypatch.setattr('app.services.cron_service.write_default_cron_jobs', fake_write_default_cron_jobs)

    marker_settings = object()
    marker_result = {'completed': True}

    assert scarf_service.update_dashboard(project_root='proj', settings=marker_settings, pipeline_result=marker_result) == '/tmp/dashboard.json'
    assert scarf_service.write_default_cron_jobs(project_root='proj') == '/tmp/jobs.json'
    assert calls == [
        ('dashboard', 'proj', marker_settings, marker_result),
        ('cron', 'proj'),
    ]
