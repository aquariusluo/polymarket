from __future__ import annotations

from datetime import datetime, timezone

from app.domain.models import Decision, LeaderTrade, MarketInfo, MISSING_CONDITION_ID, SignalDecision, normalize_side

FUTURE_TIMESTAMP_TOLERANCE_MINUTES = 5.0


class TradeFilter:
    def __init__(self, *, min_market_liquidity: float, min_time_to_expiry_hours: int, max_trade_age_minutes: int) -> None:
        self.min_market_liquidity = min_market_liquidity
        self.min_time_to_expiry_hours = min_time_to_expiry_hours
        self.max_trade_age_minutes = max_trade_age_minutes

    def evaluate(self, trade_id: int, trade: LeaderTrade, market: MarketInfo | None) -> SignalDecision:
        side = normalize_side(trade.side)
        if side is None or side.name != 'BUY':
            return SignalDecision(
                leader_trade_id=trade_id,
                condition_id=trade.condition_id or MISSING_CONDITION_ID,
                asset_id=trade.asset_id,
                decision=Decision.REJECTED,
                reason='side_not_buy',
                side=side,
                price=trade.price,
                market_slug=trade.market_slug,
            )

        if trade.condition_id is None:
            return SignalDecision(
                leader_trade_id=trade_id,
                condition_id=MISSING_CONDITION_ID,
                asset_id=trade.asset_id,
                decision=Decision.REJECTED,
                reason='missing_condition_id',
                side=side,
                price=trade.price,
                market_slug=trade.market_slug,
            )

        if market is None:
            return SignalDecision(
                leader_trade_id=trade_id,
                condition_id=trade.condition_id,
                asset_id=trade.asset_id,
                decision=Decision.REJECTED,
                reason='market_not_found',
                side=side,
                price=trade.price,
                market_slug=trade.market_slug,
            )

        if market.closed or not market.active:
            return SignalDecision(
                leader_trade_id=trade_id,
                condition_id=trade.condition_id,
                asset_id=trade.asset_id,
                decision=Decision.REJECTED,
                reason='market_inactive_or_closed',
                side=side,
                price=trade.price,
                market_slug=market.slug or trade.market_slug,
            )

        if market.liquidity is None or market.liquidity < self.min_market_liquidity:
            return SignalDecision(
                leader_trade_id=trade_id,
                condition_id=trade.condition_id,
                asset_id=trade.asset_id,
                decision=Decision.REJECTED,
                reason='liquidity_below_threshold',
                side=side,
                price=trade.price,
                market_slug=market.slug or trade.market_slug,
            )

        age_minutes = (datetime.now(timezone.utc) - trade.timestamp.astimezone(timezone.utc)).total_seconds() / 60.0
        if age_minutes < -FUTURE_TIMESTAMP_TOLERANCE_MINUTES:
            return SignalDecision(
                leader_trade_id=trade_id,
                condition_id=trade.condition_id,
                asset_id=trade.asset_id,
                decision=Decision.REJECTED,
                reason='trade_timestamp_in_future',
                side=side,
                price=trade.price,
                market_slug=market.slug or trade.market_slug,
            )

        if age_minutes > self.max_trade_age_minutes:
            return SignalDecision(
                leader_trade_id=trade_id,
                condition_id=trade.condition_id,
                asset_id=trade.asset_id,
                decision=Decision.REJECTED,
                reason='trade_too_old',
                side=side,
                price=trade.price,
                market_slug=market.slug or trade.market_slug,
            )

        if market.end_time is not None:
            now = datetime.now(timezone.utc)
            remaining_hours = (market.end_time - now).total_seconds() / 3600.0
            if remaining_hours < self.min_time_to_expiry_hours:
                return SignalDecision(
                    leader_trade_id=trade_id,
                    condition_id=trade.condition_id,
                    asset_id=trade.asset_id,
                    decision=Decision.REJECTED,
                    reason='too_close_to_expiry',
                    side=side,
                    price=trade.price,
                    market_slug=market.slug or trade.market_slug,
                )

        if trade.asset_id not in {market.yes_token_id, market.no_token_id}:
            return SignalDecision(
                leader_trade_id=trade_id,
                condition_id=trade.condition_id,
                asset_id=trade.asset_id,
                decision=Decision.REJECTED,
                reason='asset_not_in_market_tokens',
                side=side,
                price=trade.price,
                market_slug=market.slug or trade.market_slug,
            )

        return SignalDecision(
            leader_trade_id=trade_id,
            condition_id=trade.condition_id,
            asset_id=trade.asset_id,
            decision=Decision.ACCEPTED,
            reason='accepted',
            side=side,
            price=trade.price,
            market_slug=market.slug or trade.market_slug,
        )
