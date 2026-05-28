from __future__ import annotations

import uuid
from typing import Any

from app.clients.leaderboard_client import LeaderboardClient
from app.clients.polymarket_cli_client import PolymarketCliLeaderboardClient
from app.config import Settings, get_settings
from app.services.job_run_service import execute_job
from app.storage.db import get_connection, init_db
from app.storage.repositories import LeaderRepository


def run(settings: Settings | None = None, *, project_root=None, client: Any | None = None, client_cls: type | None = None, conn=None) -> dict:
    settings = settings or get_settings()

    def runner(conn) -> dict:
        selected_client_cls = client_cls or (
            PolymarketCliLeaderboardClient if settings.data_source == 'polymarket_cli' else LeaderboardClient
        )
        leaderboard_client = client or selected_client_cls()
        leaders = leaderboard_client.fetch_leaders(
            category=settings.leaderboard_category,
            time_window=settings.leaderboard_time,
            sort=settings.leaderboard_sort,
            top_n=settings.top_n,
        )
        selection_run_id = str(uuid.uuid4())
        inserted = LeaderRepository(conn).insert_many(leaders, selection_run_id=selection_run_id)
        return {
            'selection_run_id': selection_run_id,
            'leaders_fetched': len(leaders),
            'leaders_inserted': inserted,
        }

    if conn is not None:
        return execute_job(conn, job_name='select-leaders', runner=runner)
    with get_connection(settings.db_path) as own_conn:
        init_db(settings.db_path, conn=own_conn)
        return execute_job(own_conn, job_name='select-leaders', runner=runner)
