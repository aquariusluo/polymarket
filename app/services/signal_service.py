from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import sqlite3
from decimal import Decimal
from typing import Any

import httpx

from app.clients.market_client import UnsupportedMarketError
from app.config import Settings
from app.domain.money import pct, price, shares, to_decimal
from app.domain.filters import TradeFilter
from app.domain.models import Decision, LeaderTrade, MISSING_CONDITION_ID, SignalDecision
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
    REASON_CATEGORIES = {
        'wallet_excluded': 'wallet_filter',
        'market_unsupported': 'market_lookup',
        'too_close_to_expiry': 'universe_quality',
        'market_inactive_or_closed': 'universe_quality',
        'liquidity_below_threshold': 'universe_quality',
        'asset_not_in_market_tokens': 'universe_quality',
        'trade_too_old': 'eligibility',
        'side_not_buy': 'eligibility',
        'book_spread_too_wide': 'copyability',
        'book_slippage_too_high': 'copyability',
        'no_copyable_ask': 'copyability',
        'cooldown_duplicate_signal': 'cooldown',
        'cooldown_duplicate_market_signal': 'cooldown',
        'accepted': 'accepted',
    }

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

    def _signal_stage(self, decision: SignalDecision) -> str:
        if decision.reason == 'wallet_excluded':
            return 'wallet_filter'
        if decision.reason == 'market_unsupported':
            return 'market_lookup'
        if decision.reason in {'cooldown_duplicate_signal', 'cooldown_duplicate_market_signal'}:
            return 'cooldown'
        if decision.reason in {'book_spread_too_wide', 'book_slippage_too_high', 'no_copyable_ask'}:
            return 'copyability'
        if decision.decision is Decision.ACCEPTED:
            return 'copyability'
        return 'trade_filter'

    def _signal_raw_json(
        self,
        trade: LeaderTrade,
        decision: SignalDecision,
        copyability: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = dict(trade.raw_json or {})
        payload['signal_evidence'] = {
            'stage': self._signal_stage(decision),
            'category': self.REASON_CATEGORIES.get(decision.reason, 'other'),
            'decision': decision.decision.value,
            'reason': None if decision.reason == 'accepted' else decision.reason,
            'captured_at': datetime.now(timezone.utc).isoformat(),
        }
        if copyability is not None:
            payload['copyability'] = copyability
        return payload

    def _best_ask(self, book: dict) -> tuple[Decimal | None, Decimal | None]:
        asks = book.get('asks') or []
        if not asks:
            return None, None
        normalized: list[tuple[Decimal, Decimal]] = []
        for item in asks:
            if isinstance(item, dict):
                normalized.append((price(item.get('price')), shares(item.get('size', 0.0))))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                normalized.append((price(item[0]), shares(item[1])))
        if not normalized:
            return None, None
        return sorted(normalized, key=lambda x: x[0])[0]

    def _best_bid(self, book: dict) -> tuple[Decimal | None, Decimal | None]:
        bids = book.get('bids') or []
        if not bids:
            return None, None
        normalized: list[tuple[Decimal, Decimal]] = []
        for item in bids:
            if isinstance(item, dict):
                normalized.append((price(item.get('price')), shares(item.get('size', 0.0))))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                normalized.append((price(item[0]), shares(item[1])))
        if not normalized:
            return None, None
        return sorted(normalized, key=lambda x: x[0], reverse=True)[0]

    def _copyability_from_book(self, trade: LeaderTrade, decision: SignalDecision, book: dict, *, source: str) -> tuple[str | None, dict[str, Any]]:
        snapshot: dict[str, Any] = {
            'source': source,
            'captured_at': datetime.now(timezone.utc).isoformat(),
            'asset_id': decision.asset_id,
        }
        if decision.decision is not Decision.ACCEPTED or trade.price is None or trade.price <= 0:
            snapshot['eligible'] = False
            return None, snapshot
        ask_price, ask_size = self._best_ask(book)
        if ask_price is not None:
            snapshot['best_ask_price'] = float(ask_price)
        if ask_size is not None:
            snapshot['best_ask_size'] = float(ask_size)
        if ask_price is None or ask_size is None or ask_size <= 0:
            snapshot['reason'] = 'no_copyable_ask'
            return 'no_copyable_ask', snapshot
        bid_price, _ = self._best_bid(book)
        if bid_price is not None:
            snapshot['best_bid_price'] = float(bid_price)
        if bid_price is not None:
            spread = ask_price - bid_price
            snapshot['spread'] = float(spread)
            if spread >= Decimal('0.20'):
                snapshot['reason'] = 'book_spread_too_wide'
                return 'book_spread_too_wide', snapshot
        slippage_pct = pct(((ask_price - price(trade.price)) / price(trade.price)) * Decimal('100'))
        snapshot['leader_price'] = float(price(trade.price))
        snapshot['slippage_pct'] = float(slippage_pct)
        if slippage_pct > to_decimal(self.settings.max_slippage_pct):
            snapshot['reason'] = 'book_slippage_too_high'
            return 'book_slippage_too_high', snapshot
        snapshot['reason'] = None
        return None, snapshot

    def _copyability_from_snapshot(self, trade: LeaderTrade, decision: SignalDecision, snapshot: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
        if not isinstance(snapshot, dict):
            return None, None
        reason = snapshot.get('reason')
        if reason in {'no_copyable_ask', 'book_spread_too_wide', 'book_slippage_too_high'}:
            return str(reason), snapshot
        if decision.decision is not Decision.ACCEPTED or trade.price is None or trade.price <= 0:
            return None, snapshot
        ask_price = snapshot.get('best_ask_price')
        ask_size = snapshot.get('best_ask_size')
        if ask_price is None or ask_size is None or float(ask_size) <= 0:
            return 'no_copyable_ask', snapshot
        bid_price = snapshot.get('best_bid_price')
        if bid_price is not None and Decimal(str(ask_price)) - Decimal(str(bid_price)) >= Decimal('0.20'):
            return 'book_spread_too_wide', snapshot
        slippage_pct = snapshot.get('slippage_pct')
        if slippage_pct is not None and Decimal(str(slippage_pct)) > to_decimal(self.settings.max_slippage_pct):
            return 'book_slippage_too_high', snapshot
        return None, snapshot

    def copyability_rejection_reason(
        self,
        trade: LeaderTrade,
        decision: SignalDecision,
        *,
        signal_raw_json: dict[str, Any] | None = None,
    ) -> str | None:
        reason, _ = self.copyability_evidence(trade, decision, signal_raw_json=signal_raw_json)
        return reason

    def copyability_evidence(
        self,
        trade: LeaderTrade,
        decision: SignalDecision,
        *,
        signal_raw_json: dict[str, Any] | None = None,
    ) -> tuple[str | None, dict[str, Any] | None]:
        if decision.decision is not Decision.ACCEPTED or trade.price is None or trade.price <= 0:
            return None, None
        snapshot = (signal_raw_json or {}).get('copyability') if isinstance(signal_raw_json, dict) else None
        reason, evidence = self._copyability_from_snapshot(trade, decision, snapshot) if snapshot is not None else (None, None)
        if evidence is not None:
            return reason, evidence
        try:
            book = self.market_service.market_client.fetch_book(decision.asset_id)
        except httpx.HTTPError:
            return None, None
        return self._copyability_from_book(trade, decision, book, source='live_book')

    def _excluded_wallets(self) -> set[str]:
        return {str(wallet).strip().lower() for wallet in self.settings.scarf.excluded_wallets if str(wallet).strip()}

    def run(self) -> SignalRunResult:
        rows = self.trade_repo.list_without_signal(limit=self.settings.signal_batch_limit)
        excluded_wallets = self._excluded_wallets()

        processed = 0
        accepted = 0
        rejected = 0
        inserted = 0
        skipped = 0

        for row in rows:
            processed += 1
            trade = self._row_to_trade(row)

            if trade.wallet.strip().lower() in excluded_wallets:
                decision = SignalDecision(
                    leader_trade_id=int(row['id']),
                    condition_id=trade.condition_id or MISSING_CONDITION_ID,
                    asset_id=trade.asset_id,
                    decision=Decision.REJECTED,
                    reason='wallet_excluded',
                    side=trade.side,
                    price=trade.price,
                    market_slug=trade.market_slug,
                )
                inserted_now = self.signal_repo.insert_if_new(
                    trade,
                    decision,
                    raw_json=self._signal_raw_json(trade, decision),
                )
                if inserted_now:
                    inserted += 1
                    rejected += 1
                else:
                    skipped += 1
                continue

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
                    condition_id=trade.condition_id or MISSING_CONDITION_ID,
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

            copyability_reason, copyability_evidence = self.copyability_evidence(trade, decision)
            if copyability_reason is not None:
                decision = self._rejected_decision(decision, copyability_reason)
            signal_raw_json = self._signal_raw_json(trade, decision, copyability_evidence)

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
            signal_raw_json = self._signal_raw_json(trade, decision, copyability_evidence)

            inserted_now = self.signal_repo.insert_if_new(trade, decision, raw_json=signal_raw_json)
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
