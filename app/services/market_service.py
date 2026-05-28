from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3

from app.clients.market_client import MarketClient
from app.config import Settings
from app.domain.models import MarketInfo
from app.storage.repositories import MarketRepository


class MarketService:
    def __init__(self, conn: sqlite3.Connection, settings: Settings | None = None, market_client: MarketClient | None = None) -> None:
        self.conn = conn
        self.settings = settings
        self.market_client = market_client or MarketClient()
        self.market_repo = MarketRepository(conn)

    def _cache_is_fresh(self, cached: MarketInfo | None) -> bool:
        if cached is None:
            return False
        ttl_seconds = int(getattr(self.settings, 'market_cache_ttl_seconds', 300))
        if ttl_seconds <= 0 or cached.refreshed_at is None:
            return False
        age = datetime.now(timezone.utc) - cached.refreshed_at.astimezone(timezone.utc)
        return age <= timedelta(seconds=ttl_seconds)

    def get_market(self, condition_id: str) -> MarketInfo:
        cached = self.market_repo.get_by_condition_id(condition_id)
        if self._cache_is_fresh(cached):
            return cached

        market = self.market_client.fetch_market(condition_id)
        self.market_repo.upsert(market)
        return market
