from __future__ import annotations

from app.config import Settings, get_settings
from app.services.job_run_service import execute_job
from app.services.market_service import MarketService
from app.services.valuation_service import ValuationService
from app.storage.db import get_connection, init_db


def run(settings: Settings | None = None, *, project_root=None, market_service_cls=MarketService, valuation_service_cls=ValuationService, conn=None) -> dict:
    settings = settings or get_settings()

    def runner(conn) -> dict:
        market_service = market_service_cls(conn, settings)
        result = valuation_service_cls(conn, settings, market_service=market_service).mark_to_market()
        return {
            'positions_marked': result.positions_marked,
            'snapshot_id': result.snapshot_id,
        }

    if conn is not None:
        return execute_job(conn, job_name='mark-to-market', runner=runner)
    with get_connection(settings.db_path) as own_conn:
        init_db(settings.db_path, conn=own_conn)
        return execute_job(own_conn, job_name='mark-to-market', runner=runner)
