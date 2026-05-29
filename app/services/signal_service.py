from __future__ import annotations

from dataclasses import dataclass, replace
import sqlite3

import httpx

from app.clients.market_client import UnsupportedMarketError
from app.config import Settings
from app.domain.filters import TradeFilter
from app.domain.models import Decision, LeaderTrade, SignalDecision
from app.services.market_service import MarketService
from app.storage.repositories import LeaderTradeRepository, SignalRepository


@dataclass
class SignalRunResult:
    processed_count: int
    accepted_count: int
    rejected_count: int
    inserted_count: int
    skipped_count: int


class SignalService:
    def __init__(self, conn: sqlite3.Connection, settings: Settings, market_service: MarketService) -> None:
        self.conn = conn
        self.settings = settings
        self.market_service = market_service
        self.trade_repo = LeaderTradeRepository(conn)
        self.signal_repo = SignalRepository(conn)
        self.trade_filter = TradeFilter(
            min_market_liquidity=settings.min_market_liquidity,
            min_time_to_expiry_hours=settings.min_time_to_expiry_hours,
            max_trade_age_minutes=settings.max_trade_age_minutes,
        )

    def _row_to_trade(self, row) -> LeaderTrade:
        return LeaderTrade.from_row(row)

    def _rejected_decision(self, decision: SignalDecision, reason: str) -> SignalDecision:
        return replace(decision, decision=Decision.REJECTED, reason=reason)

    def run(self) -> SignalRunResult:
        rows = self.trade_repo.list_without_signal(limit=self.settings.signal_batch_limit)

        processed = 0
        accepted = 0
        rejected = 0
        inserted = 0
        skipped = 0

        for row in rows:
            processed += 1
            trade = self._row_to_trade(row)

            market = None
            unsupported_market = False
            market_unavailable = False
            if trade.condition_id is not None:
                try:
                    market = self.market_service.get_market(trade.condition_id)
                except UnsupportedMarketError:
                    unsupported_market = True
                except httpx.HTTPError:
                    market_unavailable = True

            if unsupported_market:
                decision = SignalDecision(
                    leader_trade_id=int(row['id']),
                    condition_id=trade.condition_id or '',
                    asset_id=trade.asset_id,
                    decision=Decision.REJECTED,
                    reason='market_unsupported',
                    side=trade.side,
                    price=trade.price,
                    market_slug=trade.market_slug,
                )
            elif market_unavailable:
                # Keep trade pending for retry on transient upstream outages.
                skipped += 1
                continue
            else:
                decision = self.trade_filter.evaluate(int(row['id']), trade, market)

            if decision.decision is Decision.ACCEPTED and self.signal_repo.has_recent_accepted_signal(
                wallet=trade.wallet,
                condition_id=decision.condition_id,
                asset_id=decision.asset_id,
                cooldown_minutes=self.settings.signal_cooldown_minutes,
            ):
                decision = self._rejected_decision(decision, 'cooldown_duplicate_signal')
            elif decision.decision is Decision.ACCEPTED and self.signal_repo.has_recent_accepted_market_signal(
                condition_id=decision.condition_id,
                asset_id=decision.asset_id,
                cooldown_minutes=self.settings.signal_cooldown_minutes,
            ):
                decision = self._rejected_decision(decision, 'cooldown_duplicate_market_signal')

            inserted_now = self.signal_repo.insert_if_new(trade, decision)
            if inserted_now:
                inserted += 1
                if decision.decision is Decision.ACCEPTED:
                    accepted += 1
                else:
                    rejected += 1
            else:
                skipped += 1

        return SignalRunResult(
            processed_count=processed,
            accepted_count=accepted,
            rejected_count=rejected,
            inserted_count=inserted,
            skipped_count=skipped,
        )
