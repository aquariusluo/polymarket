from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dashboard.api.routers import leaders, overview, pipeline, portfolio, signals


def create_app() -> FastAPI:
    app = FastAPI(title='Polymarket Dashboard API', version='0.1.0')
    app.add_middleware(
        CORSMiddleware,
        allow_origins=['*'],
        allow_methods=['GET'],
        allow_headers=['*'],
    )
    app.include_router(overview.router)
    app.include_router(portfolio.router)
    app.include_router(signals.router)
    app.include_router(leaders.router)
    app.include_router(pipeline.router)
    return app


app = create_app()
