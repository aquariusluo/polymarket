from __future__ import annotations

import hmac
import json
import logging
import os
import time
from collections import defaultdict, deque

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from dashboard.api.routers import leaders, overview, pipeline, portfolio, signals


def _cors_origins() -> list[str]:
    configured = os.getenv('DASHBOARD_CORS_ORIGINS', '').strip()
    if not configured:
        return [
            'http://localhost:5173',
            'http://127.0.0.1:5173',
        ]
    return [origin.strip() for origin in configured.split(',') if origin.strip()]


def create_app() -> FastAPI:
    app = FastAPI(title='Polymarket Dashboard API', version='0.1.0')
    app_env = os.getenv('APP_ENV', 'dev').strip().lower()
    dashboard_token = os.getenv('DASHBOARD_API_TOKEN', '').strip()
    if not dashboard_token and app_env not in {'dev', 'test'}:
        raise RuntimeError('DASHBOARD_API_TOKEN must be set when APP_ENV is not dev/test')
    if not dashboard_token and app_env in {'dev', 'test'}:
        logging.getLogger(__name__).warning(
            'DASHBOARD_API_TOKEN is not set; API auth is disabled for APP_ENV=%s',
            app_env,
        )

    def _apply_security_headers(response):
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        if app_env not in {'dev', 'test'}:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    # Lightweight in-memory request limiter to protect SQLite-backed endpoints.
    rate_limit_window_seconds = int(os.getenv('DASHBOARD_RATE_LIMIT_WINDOW_SECONDS', '10'))
    rate_limit_max_requests = int(os.getenv('DASHBOARD_RATE_LIMIT_MAX_REQUESTS', '120'))
    request_buckets: dict[str, deque[float]] = defaultdict(deque)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=False,
        allow_methods=['GET'],
        allow_headers=['x-dashboard-token', 'authorization', 'content-type', 'accept'],
    )

    @app.middleware("http")
    async def set_security_headers(request: Request, call_next):
        return _apply_security_headers(await call_next(request))

    @app.middleware("http")
    async def require_dashboard_token(request: Request, call_next):
        if request.method.upper() == 'OPTIONS':
            return await call_next(request)
        if not dashboard_token:
            return await call_next(request)
        provided = request.headers.get('x-dashboard-token') or ''
        auth = request.headers.get('authorization') or ''
        bearer = auth[7:].strip() if auth.lower().startswith('bearer ') else ''
        provided_ok = bool(provided) and hmac.compare_digest(provided, dashboard_token)
        bearer_ok = bool(bearer) and hmac.compare_digest(bearer, dashboard_token)
        if not provided_ok and not bearer_ok:
            return _apply_security_headers(JSONResponse({'detail': 'Unauthorized'}, status_code=401))
        return await call_next(request)

    @app.middleware("http")
    async def request_guard_and_log(request: Request, call_next):
        started = time.perf_counter()
        client_ip = request.client.host if request.client else 'unknown'
        bucket = request_buckets[client_ip]
        now = time.monotonic()
        while bucket and bucket[0] <= now - rate_limit_window_seconds:
            bucket.popleft()
        if len(bucket) >= rate_limit_max_requests:
            response = JSONResponse({'detail': 'Too Many Requests'}, status_code=429)
            response.headers['Retry-After'] = str(rate_limit_window_seconds)
            response = _apply_security_headers(response)
            logging.getLogger('dashboard.api.access').warning(
                json.dumps(
                    {
                        'event': 'request_rejected',
                        'method': request.method,
                        'path': request.url.path,
                        'status_code': response.status_code,
                        'client_ip': client_ip,
                        'reason': 'rate_limit',
                    }
                )
            )
            return response
        bucket.append(now)

        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logging.getLogger('dashboard.api.access').info(
            json.dumps(
                {
                    'event': 'request_completed',
                    'method': request.method,
                    'path': request.url.path,
                    'status_code': response.status_code,
                    'client_ip': client_ip,
                    'duration_ms': duration_ms,
                }
            )
        )
        return response

    app.include_router(overview.router)
    app.include_router(portfolio.router)
    app.include_router(signals.router)
    app.include_router(leaders.router)
    app.include_router(pipeline.router)
    return app


app = create_app()
