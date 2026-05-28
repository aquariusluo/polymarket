from __future__ import annotations

import logging
from typing import Any

from app.clients.polymarket_cli_client import PolymarketCliTradesClient
from app.clients.trades_client import TradesClient
from app.config import Settings, get_settings
from app.services.job_run_service import execute_job
from app.storage.db import get_connection, init_db
from app.storage.repositories import LeaderRepository, LeaderTradeRepository

logger = logging.getLogger(__name__)


def run(settings: Settings | None = None, *, project_root=None, trades_client: Any | None = None, trades_client_cls: type | None = None, conn=None) -> dict:
    settings = settings or get_settings()

    def runner(conn) -> dict:
        selected_client_cls = trades_client_cls or (
            PolymarketCliTradesClient if settings.data_source == 'polymarket_cli' else TradesClient
        )
        client = trades_client or selected_client_cls()
        inserted = 0
        skipped = 0
        leader_errors: list[dict[str, str]] = []
        leader_repo = LeaderRepository(conn)
        trade_repo = LeaderTradeRepository(conn)
        leaders = leader_repo.get_latest_leaders()
        if not leaders:
            raise RuntimeError("No leaders found. Run `select-leaders` first.")
        for leader in leaders:
            wallet = leader['wallet']
            leader_name = leader['pseudonym'] or leader['name'] or wallet
            try:
                trades = client.fetch_recent_trades(
                    wallet=wallet,
                    limit=settings.trade_fetch_limit,
                    leader_name=leader_name,
                )
            except Exception as exc:
                logger.warning("failed to poll leader wallet=%s leader_name=%s", wallet, leader_name, exc_info=True)
                leader_errors.append({
                    'wallet': str(wallet),
                    'leader_name': str(leader_name),
                    'error': str(exc),
                })
                continue
            for trade in trades:
                if trade_repo.insert_if_new(trade):
                    inserted += 1
                else:
                    skipped += 1
        return {
            'leaders_polled': len(leaders),
            'trades_inserted': inserted,
            'trades_skipped': skipped,
            'leader_errors': len(leader_errors),
            'leader_error_details': leader_errors,
        }

    if conn is not None:
        return execute_job(conn, job_name='poll-trades', runner=runner)
    with get_connection(settings.db_path) as own_conn:
        init_db(settings.db_path, conn=own_conn)
        return execute_job(own_conn, job_name='poll-trades', runner=runner)
