import json
from pathlib import Path

import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_get_settings_defaults():
    settings = get_settings()
    assert settings.top_n > 0
    assert settings.trade_fetch_limit > 0
    assert settings.min_market_liquidity > 0


def test_manifest_defaults_module_reads_scarf_manifest(tmp_path: Path):
    from app.config_manifest import manifest_defaults

    project_root = tmp_path / 'project'
    scarf_dir = project_root / '.scarf'
    scarf_dir.mkdir(parents=True, exist_ok=True)
    (scarf_dir / 'manifest.json').write_text(
        json.dumps(
            {
                'config': {
                    'schema': [
                        {'key': 'execution_mode', 'default': 'alert_only'},
                        {'key': 'bankroll_usd', 'default': 1234},
                        {'key': 'top_accounts_override', 'default': ['0xA', '0xB']},
                    ]
                }
            }
        ),
        encoding='utf-8',
    )

    defaults = manifest_defaults(project_root)

    assert defaults['execution_mode'] == 'alert_only'
    assert defaults['bankroll_usd'] == 1234
    assert defaults['top_accounts_override'] == ['0xA', '0xB']


def test_get_settings_rejects_db_path_outside_project_root(tmp_path: Path, monkeypatch):
    project_root = tmp_path / 'project'
    project_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv('DB_PATH', str(tmp_path / 'escape.db'))

    with pytest.raises(ValueError, match='DB_PATH must stay within project root'):
        get_settings(project_root)



def test_get_settings_exposes_structured_scarf_config(tmp_path: Path, monkeypatch):
    project_root = tmp_path / 'project'
    scarf_dir = project_root / '.scarf'
    scarf_dir.mkdir(parents=True, exist_ok=True)
    (scarf_dir / 'manifest.json').write_text(
        json.dumps(
            {
                'config': {
                    'schema': [
                        {'key': 'execution_mode', 'default': 'alert_only'},
                        {'key': 'bankroll_usd', 'default': 1234},
                        {'key': 'max_daily_orders', 'default': 9},
                        {'key': 'evaluation_days', 'default': 45},
                        {'key': 'top_accounts_override', 'default': ['0xA', '0xB']},
                        {'key': 'excluded_wallets', 'default': ['0xBAD']},
                        {'key': 'operator_notes', 'default': 'Stay conservative'},
                        {'key': 'leader_selection_mode', 'default': 'fixed_override'},
                        {'key': 'leaderboard_source', 'default': 'Custom leaderboard'},
                        {'key': 'evaluation_start_date', 'default': '2026-05-01'},
                    ]
                }
            }
        ),
        encoding='utf-8',
    )
    monkeypatch.chdir(project_root)

    settings = get_settings()

    assert settings.scarf.execution_mode == 'alert_only'
    assert settings.scarf.bankroll_usd == 1234.0
    assert settings.scarf.max_daily_orders == 9
    assert settings.scarf.evaluation_days == 45
    assert settings.scarf.top_accounts_override == ('0xA', '0xB')
    assert settings.scarf.excluded_wallets == ('0xBAD',)
    assert settings.scarf.operator_notes == 'Stay conservative'
    assert settings.scarf.leader_selection_mode == 'fixed_override'
    assert settings.scarf.leaderboard_source == 'Custom leaderboard'
    assert settings.scarf.evaluation_start_date == '2026-05-01'
    assert settings.scarf_execution_mode == settings.scarf.execution_mode
    assert settings.scarf_bankroll_usd == settings.scarf.bankroll_usd



def test_runtime_modules_use_structured_scarf_config_access():
    app_root = Path(__file__).resolve().parents[1] / 'app'
    offenders = []
    for path in app_root.rglob('*.py'):
        if path.name == 'config.py':
            continue
        text = path.read_text(encoding='utf-8')
        if 'settings.scarf_' in text:
            offenders.append(path.relative_to(app_root).as_posix())

    assert offenders == []


def test_get_settings_supports_max_slippage_bps_env(tmp_path: Path, monkeypatch):
    project_root = tmp_path / 'project'
    project_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv('MAX_SLIPPAGE_BPS', '50')
    monkeypatch.chdir(project_root)

    settings = get_settings(project_root)

    assert settings.max_slippage_pct == 0.5
