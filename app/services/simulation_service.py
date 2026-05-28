from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import logging
import sqlite3

import httpx

from app.config import Settings
from app.domain.money import money, pct, price, shares, to_decimal, to_float
from app.services.market_service import MarketService
from app.storage.repositories import PositionRepository, SignalRepository, SimOrderRepository

logger = logging.getLogger(__name__)


@dataclass
class SimulationRunResult:
    processed_count: int
    filled_count: int
    rejected_count: int
    inserted_orders: int


class SimulationService:
    def __init__(self, conn: sqlite3.Connection, settings: Settings, market_service: MarketService) -> None:
        self.conn = conn
        self.settings = settings
        self.market_service = market_service
        self.signal_repo = SignalRepository(conn)
        self.order_repo = SimOrderRepository(conn)
        self.position_repo = PositionRepository(conn)

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
        first = sorted(normalized, key=lambda x: x[0])[0]
        return first

    def _reject(self, *, signal_id: int, condition_id: str, asset_id: str, market_slug: str | None, side: str | None,
                requested_notional: Decimal, leader_price: Decimal | None, reason: str, fill_price: Decimal | None = None,
                slippage_pct: Decimal | None = None) -> None:
        self.order_repo.insert(
            signal_id=signal_id,
            condition_id=condition_id,
            asset_id=asset_id,
            market_slug=market_slug,
            side=side,
            requested_notional=to_float(money(requested_notional)),
            filled_notional=to_float(money(0)),
            filled_shares=to_float(shares(0)),
            fill_price=to_float(price(fill_price)) if fill_price is not None else None,
            leader_price=to_float(price(leader_price)) if leader_price is not None else None,
            slippage_pct=to_float(pct(slippage_pct)) if slippage_pct is not None else None,
            status='rejected',
            reason=reason,
        )

    def run(self) -> SimulationRunResult:
        rows = self.signal_repo.list_pending_accepted(limit=500)
        processed = filled = rejected = inserted_orders = 0

        for row in rows:
            processed += 1
            condition_id = str(row['condition_id'])
            asset_id = str(row['asset_id'])
            market_slug = row['market_slug']
            side = row['side']
            leader_price = price(row['leader_price']) if row['leader_price'] is not None else None
            requested_notional = money(self.settings.fixed_trade_usdc)
            signal_id = int(row['id'])

            start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            filled_today = self.order_repo.count_filled_since(start_of_day)
            if filled_today >= int(self.settings.scarf.max_daily_orders):
                self._reject(
                    signal_id=signal_id, condition_id=condition_id, asset_id=asset_id,
                    market_slug=market_slug, side=side, requested_notional=requested_notional,
                    leader_price=leader_price, reason='max_daily_orders_exceeded',
                )
                inserted_orders += 1
                rejected += 1
                continue

            bankroll = money(self.settings.scarf.bankroll_usd)
            if bankroll <= 0:
                self._reject(
                    signal_id=signal_id, condition_id=condition_id, asset_id=asset_id,
                    market_slug=market_slug, side=side, requested_notional=requested_notional,
                    leader_price=leader_price, reason='bankroll_not_configured',
                )
                inserted_orders += 1
                rejected += 1
                continue

            total_cost_basis = money(self.position_repo.total_cost_basis())
            remaining_bankroll = money(bankroll - total_cost_basis)
            if remaining_bankroll <= 0 or requested_notional > remaining_bankroll:
                self._reject(
                    signal_id=signal_id, condition_id=condition_id, asset_id=asset_id,
                    market_slug=market_slug, side=side, requested_notional=requested_notional,
                    leader_price=leader_price, reason='bankroll_exceeded',
                )
                inserted_orders += 1
                rejected += 1
                continue

            current_cost = money(self.position_repo.current_market_cost_basis(condition_id))
            remaining_capacity = money(to_decimal(self.settings.per_market_cap_usdc) - current_cost)
            if remaining_capacity <= 0:
                self._reject(
                    signal_id=signal_id, condition_id=condition_id, asset_id=asset_id,
                    market_slug=market_slug, side=side, requested_notional=requested_notional,
                    leader_price=leader_price, reason='per_market_cap_exceeded',
                )
                inserted_orders += 1
                rejected += 1
                continue

            if leader_price is None or leader_price <= 0:
                self._reject(
                    signal_id=signal_id, condition_id=condition_id, asset_id=asset_id,
                    market_slug=market_slug, side=side, requested_notional=requested_notional,
                    leader_price=leader_price, reason='missing_leader_price',
                )
                inserted_orders += 1
                rejected += 1
                continue

            try:
                book = self.market_service.market_client.fetch_book(asset_id)
            except httpx.HTTPError:
                self._reject(
                    signal_id=signal_id, condition_id=condition_id, asset_id=asset_id,
                    market_slug=market_slug, side=side, requested_notional=requested_notional,
                    leader_price=leader_price, reason='book_unavailable',
                )
                inserted_orders += 1
                rejected += 1
                continue

            ask_price, ask_size = self._best_ask(book)
            if ask_price is None or ask_size is None or ask_size <= 0:
                self._reject(
                    signal_id=signal_id, condition_id=condition_id, asset_id=asset_id,
                    market_slug=market_slug, side=side, requested_notional=requested_notional,
                    leader_price=leader_price, reason='no_ask_depth',
                )
                inserted_orders += 1
                rejected += 1
                continue

            slippage_pct = pct(((ask_price - leader_price) / leader_price) * Decimal('100'))
            if abs(slippage_pct) > to_decimal(self.settings.max_slippage_pct):
                self._reject(
                    signal_id=signal_id, condition_id=condition_id, asset_id=asset_id,
                    market_slug=market_slug, side=side, requested_notional=requested_notional,
                    leader_price=leader_price, reason='slippage_too_high', fill_price=ask_price,
                    slippage_pct=slippage_pct,
                )
                inserted_orders += 1
                rejected += 1
                continue

            max_fillable_notional = money(ask_price * ask_size)
            filled_notional = money(min(requested_notional, max_fillable_notional, remaining_capacity))
            filled_shares = shares(filled_notional / ask_price)

            if filled_notional <= 0 or filled_shares <= 0:
                self._reject(
                    signal_id=signal_id, condition_id=condition_id, asset_id=asset_id,
                    market_slug=market_slug, side=side, requested_notional=requested_notional,
                    leader_price=leader_price, reason='no_ask_depth',
                )
                inserted_orders += 1
                rejected += 1
                continue

            deferred_rejection_reason: str | None = None
            try:
                with self.conn:
                    refreshed_filled_today = self.order_repo.count_filled_since(start_of_day)
                    if refreshed_filled_today >= self.settings.scarf.max_daily_orders:
                        deferred_rejection_reason = 'max_daily_orders_exceeded'
                    else:
                        refreshed_total_cost = money(self.position_repo.total_cost_basis())
                        refreshed_remaining_bankroll = money(bankroll - refreshed_total_cost)
                        if refreshed_remaining_bankroll <= 0 or requested_notional > refreshed_remaining_bankroll:
                            deferred_rejection_reason = 'bankroll_exceeded'
                        else:
                            refreshed_current_cost = money(self.position_repo.current_market_cost_basis(condition_id))
                            refreshed_remaining_capacity = money(to_decimal(self.settings.per_market_cap_usdc) - refreshed_current_cost)
                            if refreshed_remaining_capacity <= 0:
                                deferred_rejection_reason = 'per_market_cap_exceeded'
                            else:
                                refreshed_filled_notional = money(
                                    min(filled_notional, refreshed_remaining_capacity, refreshed_remaining_bankroll)
                                )
                                refreshed_filled_shares = shares(refreshed_filled_notional / ask_price)
                                if refreshed_filled_notional <= 0 or refreshed_filled_shares <= 0:
                                    deferred_rejection_reason = 'per_market_cap_exceeded'
                                else:
                                    self.order_repo.insert_in_tx(
                                        signal_id=signal_id,
                                        condition_id=condition_id,
                                        asset_id=asset_id,
                                        market_slug=market_slug,
                                        side=side,
                                        requested_notional=to_float(requested_notional),
                                        filled_notional=to_float(refreshed_filled_notional),
                                        filled_shares=to_float(refreshed_filled_shares),
                                        fill_price=to_float(ask_price),
                                        leader_price=to_float(leader_price),
                                        slippage_pct=to_float(slippage_pct),
                                        status='filled',
                                        reason='filled',
                                    )
                                    self.position_repo.upsert_buy(
                                        condition_id,
                                        asset_id,
                                        market_slug,
                                        side,
                                        to_float(refreshed_filled_shares),
                                        to_float(ask_price),
                                        commit=False,
                                    )
                                    inserted_orders += 1
                                    filled += 1
            except Exception:
                logger.exception("failed to fill signal_id=%s", signal_id)
                deferred_rejection_reason = 'processing_error'

            if deferred_rejection_reason is not None:
                if deferred_rejection_reason == 'processing_error':
                    try:
                        self._reject(
                            signal_id=signal_id,
                            condition_id=condition_id,
                            asset_id=asset_id,
                            market_slug=market_slug,
                            side=side,
                            requested_notional=requested_notional,
                            leader_price=leader_price,
                            reason='processing_error',
                        )
                        inserted_orders += 1
                        rejected += 1
                    except Exception:
                        logger.exception("failed to record processing_error rejection for signal_id=%s", signal_id)
                    continue
                self._reject(
                    signal_id=signal_id,
                    condition_id=condition_id,
                    asset_id=asset_id,
                    market_slug=market_slug,
                    side=side,
                    requested_notional=requested_notional,
                    leader_price=leader_price,
                    reason=deferred_rejection_reason,
                )
                inserted_orders += 1
                rejected += 1
                continue

        return SimulationRunResult(
            processed_count=processed,
            filled_count=filled,
            rejected_count=rejected,
            inserted_orders=inserted_orders,
        )
