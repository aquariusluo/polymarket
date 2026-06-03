from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from dashboard.api.main import create_app
from dashboard.api.routers import overview as overview_router
from dashboard.api.database import get_db
from app.storage.db import get_connection, init_db


def _write_project_reports(project_root: Path) -> None:
    reports_dir = project_root / '.scarf' / 'reports'
    reports_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = project_root / '.scarf' / 'manifest.json'
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    latest_summary = {
        'total_equity': 110.0,
        'total_unrealized_pnl': 10.0,
        'total_realized_pnl': 5.0,
        'drawdown_pct': 2.5,
        'open_position_count': 1,
        'accepted_signal_count': 4,
        'filled_order_count': 1,
        'rejected_order_count': 2,
        'signal_rejection_reasons': {'signal_stale': 2},
        'execution_rejection_reasons': {'book_unavailable': 1},
        'execution_suppression_reasons': {'execution_mode_alert_only': 3},
    }
    auto_follow_gate = {
        'status': 'hold',
        'decision': 'manual_confirm_only',
        'notes': ['Only 0 fills in 72h window.'],
        'thresholds': {'min_filled_orders_window': 10},
    }
    manifest = {
        'execution_mode': 'manual_confirm',
        'bankroll_usd': 1000.0,
    }

    (reports_dir / 'latest-summary.json').write_text(json.dumps(latest_summary), encoding='utf-8')
    (reports_dir / 'auto-follow-gate.json').write_text(json.dumps(auto_follow_gate), encoding='utf-8')
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')


def test_overview_endpoint_includes_reason_summary_fields(tmp_path, monkeypatch):
    project_root = tmp_path / 'project'
    db_path = project_root / 'data.db'
    init_db(str(db_path))
    _write_project_reports(project_root)

    with get_connection(str(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS job_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                inserted_count INTEGER DEFAULT 0,
                skipped_count INTEGER DEFAULT 0,
                error_message TEXT
            )
            """
        )
        conn.commit()

    monkeypatch.delenv('DASHBOARD_API_TOKEN', raising=False)
    monkeypatch.setattr(overview_router, 'PROJECT_ROOT', project_root)

    app = create_app()

    def override_get_db():
        conn = get_connection(str(db_path))
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = override_get_db

    client = TestClient(app)
    response = client.get('/api/overview')

    assert response.status_code == 200
    payload = response.json()
    assert payload['signal_rejection_reasons'] == {'signal_stale': 2}
    assert payload['execution_rejection_reasons'] == {'book_unavailable': 1}
    assert payload['execution_suppression_reasons'] == {'execution_mode_alert_only': 3}
