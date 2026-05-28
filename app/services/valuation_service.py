from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from typing import Any

import httpx

from app.config import Settings
from app.domain.money import money, price, shares, to_decimal, to_float
from app.services.market_service import MarketService
from app.storage.repositories import PortfolioSnapshotRepository, PositionRepository


@dataclass
class ValuationRunResult:
    positions_marked: int
    snapshot_id: int | None


class ValuationService:
    def __init__(self, conn: sqlite3.Connection, settings: Settings, market_service: MarketService):
        self.conn = conn
        self.settings = settings
        self.market_service = market_service
        self.position_repo = PositionRepository(conn)
        self.snapshot_repo = PortfolioSnapshotRepository(conn)

    def _best_bid(self, token_id: str) -> float:
        book = self.market_service.market_client.fetch_book(token_id)
        bids = book.get('bids') or []
        if not bids:
            raise RuntimeError(f'missing bid for token {token_id}')
        bid_prices = [price(bid['price']) for bid in bids if isinstance(bid, dict) and bid.get('price') is not None]
        if not bid_prices:
            raise RuntimeError(f'missing parsable bid for token {token_id}')
        bid = sorted(bid_prices, reverse=True)[0]
        return to_float(bid)

    def _resolved_payout_price(self, position_asset_id: str, market_raw_json: dict[str, Any]) -> float | None:
        clob = market_raw_json.get('clob') if isinstance(market_raw_json, dict) else None
        tokens = clob.get('tokens') if isinstance(clob, dict) else None
        if not isinstance(tokens, list):
            return None
        for token in tokens:
            if not isinstance(token, dict):
                continue
            token_id = str(token.get('token_id', ''))
            if token_id != str(position_asset_id):
                continue
            winner = token.get('winner')
            if winner is True:
                return 1.0
            if winner is False:
                return 0.0
            return None
        return None

    def mark_to_market(self) -> ValuationRunResult:
        positions = self.position_repo.list_all()
        total_cost_basis = money(0)
        total_market_value = money(0)
        raw_positions: list[dict[str, Any]] = []
        mark_errors: list[dict[str, Any]] = []
        settled_positions: list[dict[str, Any]] = []
        positions_marked = 0

        for position in positions:
            market_info = None
            if position.condition_id and hasattr(self.market_service, 'get_market'):
                try:
                    market_info = self.market_service.get_market(position.condition_id)
                except (httpx.HTTPError, RuntimeError):
                    market_info = None

            if market_info is not None and market_info.closed:
                payout = self._resolved_payout_price(position.asset_id, market_info.raw_json)
                if payout is not None:
                    payout_price = price(payout)
                    settled_value = money(shares(position.shares) * payout_price)
                    settled_pnl = money(settled_value - money(position.cost_basis))
                    settled_positions.append(
                        {
                            'condition_id': position.condition_id,
                            'asset_id': position.asset_id,
                            'shares': position.shares,
                            'cost_basis': position.cost_basis,
                            'settled_price': to_float(payout_price),
                            'settled_value': to_float(settled_value),
                            'realized_pnl': to_float(settled_pnl),
                        }
                    )
                    continue

            try:
                mark_price = price(self._best_bid(position.asset_id))
            except (httpx.HTTPError, RuntimeError) as exc:
                mark_errors.append(
                    {
                        'condition_id': position.condition_id,
                        'asset_id': position.asset_id,
                        'error': str(exc),
                    }
                )
                continue
            market_value = money(shares(position.shares) * mark_price)
            unrealized = money(market_value - money(position.cost_basis))
            total_cost_basis = money(total_cost_basis + money(position.cost_basis))
            total_market_value = money(total_market_value + market_value)
            positions_marked += 1
            raw_positions.append(
                {
                    'condition_id': position.condition_id,
                    'asset_id': position.asset_id,
                    'shares': position.shares,
                    'avg_cost': position.avg_cost,
                    'cost_basis': position.cost_basis,
                    'mark_price': to_float(mark_price),
                    'market_value': to_float(market_value),
                    'unrealized_pnl': to_float(unrealized),
                }
            )

        total_unrealized = money(total_market_value - total_cost_basis)
        latest_snapshot = self.snapshot_repo.latest()
        prior_realized = money(latest_snapshot.total_realized_pnl) if latest_snapshot is not None else money(0)
        settled_realized_delta = money(
            sum((to_decimal(item['realized_pnl']) for item in settled_positions), to_decimal(0))
        )
        total_realized = money(prior_realized + settled_realized_delta)
        bankroll = money(getattr(self.settings, 'scarf_bankroll_usd', 0))
        uncommitted_bankroll = max(money(0), bankroll - total_cost_basis)
        total_equity = money(total_market_value + total_realized + uncommitted_bankroll)
        drawdown_pct = self.snapshot_repo.compute_drawdown_pct(to_float(total_equity))
        with self.conn:
            for item in settled_positions:
                self.position_repo.delete(str(item['condition_id']), str(item['asset_id']), commit=False)
            snapshot_id = self.snapshot_repo.insert(
                total_cost_basis=to_float(total_cost_basis),
                total_market_value=to_float(total_market_value),
                total_unrealized_pnl=to_float(total_unrealized),
                total_realized_pnl=to_float(total_realized),
                total_equity=to_float(total_equity),
                drawdown_pct=drawdown_pct,
                raw_json={
                    'positions': raw_positions,
                    'mark_errors': mark_errors,
                    'settled_positions': settled_positions,
                    'settled_realized_delta': to_float(settled_realized_delta),
                },
                commit=False,
            )
        return ValuationRunResult(positions_marked=positions_marked, snapshot_id=snapshot_id)
