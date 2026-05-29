from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dashboard.api.main import create_app
from dashboard.api.routers import pipeline as pipeline_router


def test_dashboard_api_without_token_env_allows_requests(monkeypatch):
    monkeypatch.delenv('DASHBOARD_API_TOKEN', raising=False)
    app = create_app()
    client = TestClient(app)

    response = client.get('/api/__nonexistent__')
    assert response.status_code == 404


def test_dashboard_api_warns_when_token_missing_in_test(monkeypatch, caplog):
    monkeypatch.setenv('APP_ENV', 'test')
    monkeypatch.delenv('DASHBOARD_API_TOKEN', raising=False)
    caplog.set_level('WARNING')

    create_app()

    assert any('API auth is disabled' in rec.message for rec in caplog.records)


def test_dashboard_api_rejects_requests_without_token_header(monkeypatch):
    monkeypatch.setenv('DASHBOARD_API_TOKEN', 'secret-token')
    app = create_app()
    client = TestClient(app)

    response = client.get('/api/__nonexistent__')
    assert response.status_code == 401
    assert response.headers.get('x-frame-options') == 'DENY'
    assert response.headers.get('x-content-type-options') == 'nosniff'
    assert response.headers.get('referrer-policy') == 'strict-origin-when-cross-origin'


def test_dashboard_api_accepts_requests_with_token_header(monkeypatch):
    monkeypatch.setenv('DASHBOARD_API_TOKEN', 'secret-token')
    app = create_app()
    client = TestClient(app)

    response = client.get('/api/__nonexistent__', headers={'x-dashboard-token': 'secret-token'})
    assert response.status_code == 404


def test_dashboard_api_accepts_requests_with_lowercase_bearer_token(monkeypatch):
    monkeypatch.setenv('DASHBOARD_API_TOKEN', 'secret-token')
    app = create_app()
    client = TestClient(app)

    response = client.get('/api/__nonexistent__', headers={'authorization': 'bearer secret-token'})
    assert response.status_code == 404


def test_dashboard_api_requires_token_outside_dev_and_test(monkeypatch):
    monkeypatch.delenv('DASHBOARD_API_TOKEN', raising=False)
    monkeypatch.setenv('APP_ENV', 'prod')

    with pytest.raises(RuntimeError, match='DASHBOARD_API_TOKEN must be set'):
        create_app()


def test_dashboard_api_sets_security_headers(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'test')
    monkeypatch.setenv('DASHBOARD_API_TOKEN', 'secret-token')
    app = create_app()
    client = TestClient(app)

    response = client.get('/api/__nonexistent__', headers={'x-dashboard-token': 'secret-token'})
    assert response.status_code == 404
    assert response.headers.get('x-frame-options') == 'DENY'
    assert response.headers.get('x-content-type-options') == 'nosniff'
    assert response.headers.get('referrer-policy') == 'strict-origin-when-cross-origin'


def test_dashboard_api_sets_hsts_in_prod(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'prod')
    monkeypatch.setenv('DASHBOARD_API_TOKEN', 'secret-token')
    app = create_app()
    client = TestClient(app)

    response = client.get('/api/__nonexistent__', headers={'x-dashboard-token': 'secret-token'})
    assert response.status_code == 404
    assert response.headers.get('strict-transport-security') == 'max-age=31536000; includeSubDomains'


def test_dashboard_api_uses_env_configured_cors_origins(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'test')
    monkeypatch.setenv('DASHBOARD_API_TOKEN', 'secret-token')
    monkeypatch.setenv('DASHBOARD_CORS_ORIGINS', 'http://example.com,http://localhost:5173')
    app = create_app()
    client = TestClient(app)

    response = client.options(
        '/api/__nonexistent__',
        headers={
            'Origin': 'http://example.com',
            'Access-Control-Request-Method': 'GET',
            'x-dashboard-token': 'secret-token',
        },
    )
    assert response.status_code == 200
    assert response.headers.get('access-control-allow-origin') == 'http://example.com'


def test_dashboard_api_cors_preflight_without_token_is_allowed(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'test')
    monkeypatch.setenv('DASHBOARD_API_TOKEN', 'secret-token')
    monkeypatch.setenv('DASHBOARD_CORS_ORIGINS', 'http://example.com')
    app = create_app()
    client = TestClient(app)

    response = client.options(
        '/api/__nonexistent__',
        headers={
            'Origin': 'http://example.com',
            'Access-Control-Request-Method': 'GET',
        },
    )
    assert response.status_code == 200
    assert response.headers.get('access-control-allow-origin') == 'http://example.com'


def test_pipeline_runs_sanitizes_error_message(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'test')
    monkeypatch.setenv('DASHBOARD_API_TOKEN', 'secret-token')
    app = create_app()

    conn = sqlite3.connect(':memory:', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE job_runs (
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
    long_msg = 'x' * 260
    conn.execute(
        """
        INSERT INTO job_runs (job_name, started_at, finished_at, status, inserted_count, skipped_count, error_message)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ('demo-job', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:05+00:00', 'failed', 0, 0, long_msg),
    )
    conn.commit()

    def _fake_get_db():
        try:
            yield conn
        finally:
            pass

    app.dependency_overrides[pipeline_router.get_db] = _fake_get_db
    client = TestClient(app)
    response = client.get('/api/pipeline/runs', headers={'x-dashboard-token': 'secret-token'})
    app.dependency_overrides.clear()
    conn.close()

    assert response.status_code == 200
    runs = response.json()
    assert len(runs) == 1
    assert runs[0]['status'] == 'failed'
    assert isinstance(runs[0]['error_message'], str)
    assert len(runs[0]['error_message']) == 200


def test_pipeline_monitor_rejects_outside_tmp_path(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'test')
    monkeypatch.setenv('DASHBOARD_API_TOKEN', 'secret-token')
    monkeypatch.setattr(pipeline_router, 'MONITOR_LOG', Path('/etc/hosts'))
    app = create_app()
    client = TestClient(app)

    response = client.get('/api/pipeline/monitor', headers={'x-dashboard-token': 'secret-token'})
    assert response.status_code == 500
    assert response.json().get('detail') == 'Invalid monitor log path'
