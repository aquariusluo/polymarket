from __future__ import annotations

from app.config import Settings, get_settings
from app.services.job_run_service import execute_job
from app.services.market_service import MarketService
from app.services.simulation_service import SimulationService
from app.storage.db import get_connection, init_db
from app.storage.repositories import SignalRepository, SimOrderRepository


def run(settings: Settings | None = None, *, project_root=None, market_service_cls=MarketService, simulation_service_cls=SimulationService, conn=None) -> dict:
    settings = settings or get_settings()

    def runner(conn) -> dict:
        if settings.scarf.execution_mode == 'alert_only':
            signal_repo = SignalRepository(conn)
            order_repo = SimOrderRepository(conn)
            suppressed = 0
            for row in signal_repo.list_pending_accepted(limit=500):
                order_repo.insert(
                    signal_id=int(row['id']),
                    condition_id=str(row['condition_id']),
                    asset_id=str(row['asset_id']),
                    market_slug=row['market_slug'],
                    side=row['side'],
                    requested_notional=float(settings.fixed_trade_usdc),
                    filled_notional=0.0,
                    filled_shares=0.0,
                    fill_price=None,
                    leader_price=float(row['leader_price']) if row['leader_price'] is not None else None,
                    slippage_pct=None,
                    status='suppressed',
                    reason='execution_mode_alert_only',
                )
                suppressed += 1
            return {
                'processed': suppressed,
                'filled': 0,
                'rejected': 0,
                'inserted_orders': suppressed,
                'suppressed': suppressed,
            }
        market_service = market_service_cls(conn, settings)
        result = simulation_service_cls(conn, settings, market_service=market_service).run()
        return {
            'processed': result.processed_count,
            'filled': result.filled_count,
            'rejected': result.rejected_count,
            'inserted_orders': result.inserted_orders,
        }

    if conn is not None:
        return execute_job(conn, job_name='simulate', runner=runner)
    with get_connection(settings.db_path) as own_conn:
        init_db(settings.db_path, conn=own_conn)
        return execute_job(own_conn, job_name='simulate', runner=runner)
