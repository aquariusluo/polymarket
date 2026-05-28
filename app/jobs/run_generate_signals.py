from __future__ import annotations

from app.config import Settings, get_settings
from app.services.job_run_service import execute_job
from app.services.market_service import MarketService
from app.services.signal_service import SignalService
from app.storage.db import get_connection, init_db


def run(settings: Settings | None = None, *, project_root=None, market_service_cls=MarketService, signal_service_cls=SignalService, conn=None) -> dict:
    settings = settings or get_settings()

    def runner(conn) -> dict:
        market_service = market_service_cls(conn, settings)
        result = signal_service_cls(conn, settings, market_service=market_service).run()
        return {
            'processed': result.processed_count,
            'accepted': result.accepted_count,
            'rejected': result.rejected_count,
            'inserted': result.inserted_count,
            'skipped': result.skipped_count,
        }

    if conn is not None:
        return execute_job(conn, job_name='generate-signals', runner=runner)
    with get_connection(settings.db_path) as own_conn:
        init_db(settings.db_path, conn=own_conn)
        return execute_job(own_conn, job_name='generate-signals', runner=runner)
