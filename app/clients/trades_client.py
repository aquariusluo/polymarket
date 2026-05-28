from __future__ import annotations

from typing import Any

import httpx

from app.clients.base_client import BasePolymarketClient
from app.domain.models import LeaderTrade, parse_datetime


class TradesClient(BasePolymarketClient):
    def __init__(
        self,
        base_url: str = "https://data-api.polymarket.com",
        timeout: float = 20.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        super().__init__(base_url=base_url, timeout=timeout, http_client=http_client)

    def _parse_trade(self, row: dict[str, Any], leader_name: str | None) -> LeaderTrade:
        tx_hash = row.get("transactionHash") or row.get("transaction_hash") or row.get("txHash")
        if not tx_hash:
            raise RuntimeError(f"Missing transaction hash in trade row: {row}")

        wallet = row.get("user") or row.get("wallet") or row.get("proxyWallet") or row.get("owner")
        if not wallet:
            raise RuntimeError(f"Missing wallet in trade row: {row}")

        timestamp = row.get("timestamp") or row.get("createdAt") or row.get("time")
        if not timestamp:
            raise RuntimeError(f"Missing timestamp in trade row: {row}")

        asset_id = row.get("assetId") or row.get("asset_id") or row.get("asset")
        if asset_id is None:
            raise RuntimeError(f"Missing asset_id in trade row: {row}")

        parsed_timestamp = parse_datetime(timestamp)
        if parsed_timestamp is None:
            raise RuntimeError(f"Missing timestamp in trade row: {row}")

        return LeaderTrade(
            wallet=str(wallet),
            leader_name=leader_name,
            transaction_hash=str(tx_hash),
            condition_id=str(row.get("conditionId")) if row.get("conditionId") is not None else None,
            asset_id=str(asset_id),
            side=str(row.get("side")) if row.get("side") is not None else None,
            size=float(row["size"]) if row.get("size") is not None else None,
            price=float(row["price"]) if row.get("price") is not None else None,
            timestamp=parsed_timestamp,
            market_title=str(row.get("title") or row.get("marketTitle")) if (row.get("title") or row.get("marketTitle")) is not None else None,
            market_slug=str(row.get("slug") or row.get("marketSlug")) if (row.get("slug") or row.get("marketSlug")) is not None else None,
            raw_json=row,
        )

    def fetch_recent_trades(
        self,
        wallet: str,
        limit: int = 50,
        leader_name: str | None = None,
    ) -> list[LeaderTrade]:
        url = f"{self.base_url}/trades"
        payload = self._get_json(url, params={"user": wallet, "limit": limit})

        if not isinstance(payload, list):
            raise RuntimeError(f"Unexpected trades payload type: {type(payload)}")

        trades: list[LeaderTrade] = []
        for row in payload:
            if not isinstance(row, dict):
                raise RuntimeError(f"Unexpected trade row type: {type(row)}")
            trades.append(self._parse_trade(row, leader_name=leader_name))

        return trades
