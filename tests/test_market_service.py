from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import Settings
from app.domain.models import MarketInfo
from app.services.market_service import MarketService
from app.storage.db import get_connection, init_db
from app.storage.repositories import MarketRepository


class RefreshingMarketClient:
    def __init__(self):
        self.calls = 0

    def fetch_market(self, condition_id: str) -> MarketInfo:
        self.calls += 1
        return MarketInfo(
            condition_id=condition_id,
            title='Will X happen?',
            slug='will-x-happen',
            end_time=datetime.now(timezone.utc) + timedelta(days=3),
            liquidity=10000.0 + self.calls,
            active=True,
            closed=False,
            yes_token_id='asset_yes',
            no_token_id='asset_no',
            yes_outcome='Yes',
            no_outcome='No',
            raw_json={'call': self.calls},
        )


def _settings(db_path: str, ttl_seconds: int) -> Settings:
    return Settings(
        app_env='test',
        db_path=db_path,
        leaderboard_category='overall',
        leaderboard_time='30d',
        leaderboard_sort='profit',
        top_n=5,
        poll_interval_seconds=10,
        trade_fetch_limit=50,
        min_time_to_expiry_hours=24,
        min_market_liquidity=10000,
        signal_cooldown_minutes=5,
        market_cache_ttl_seconds=ttl_seconds,
    )


def test_market_service_refreshes_stale_cache(tmp_path: Path):
    db_path = tmp_path / 'market.db'
    init_db(str(db_path))
    client = RefreshingMarketClient()

    with get_connection(str(db_path)) as conn:
        repo = MarketRepository(conn)
        repo.upsert(
            MarketInfo(
                condition_id='cond1',
                title='Old',
                slug='old-slug',
                end_time=datetime.now(timezone.utc) + timedelta(days=1),
                liquidity=1.0,
                active=False,
                closed=True,
                yes_token_id='old_yes',
                no_token_id='old_no',
                yes_outcome='Yes',
                no_outcome='No',
                raw_json={'stale': True},
            )
        )
        conn.execute("UPDATE markets SET refreshed_at = datetime('now', '-2 hours') WHERE condition_id = ?", ('cond1',))
        conn.commit()

        market = MarketService(conn, settings=_settings(str(db_path), ttl_seconds=60), market_client=client).get_market('cond1')

        assert client.calls == 1
        assert market.active is True
        assert market.closed is False
        assert market.raw_json == {'call': 1}
