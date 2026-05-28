from __future__ import annotations

from typing import Any

import httpx

from app.clients.base_client import BasePolymarketClient
from app.domain.models import MarketInfo, parse_datetime


class UnsupportedMarketError(RuntimeError):
    pass


class MarketClient:
    def __init__(
        self,
        gamma_url: str = "https://gamma-api.polymarket.com",
        clob_url: str = "https://clob.polymarket.com",
        timeout: float = 20.0,
        gamma_client: httpx.Client | None = None,
        clob_client: httpx.Client | None = None,
    ) -> None:
        self.gamma_url = gamma_url.rstrip("/")
        self.clob_url = clob_url.rstrip("/")
        self.gamma = BasePolymarketClient(base_url=self.gamma_url, timeout=timeout, http_client=gamma_client)
        self.clob = BasePolymarketClient(base_url=self.clob_url, timeout=timeout, http_client=clob_client)

    def _get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        client = self.gamma if url.startswith(self.gamma_url) else self.clob
        return client._get_json(url, params=params)

    def fetch_gamma_market(self, condition_id: str) -> dict[str, Any] | None:
        payload = self._get_json(
            f"{self.gamma_url}/markets",
            params={"condition_ids": condition_id},
        )
        if isinstance(payload, list) and payload:
            row = payload[0]
            if isinstance(row, dict):
                return row
        return None

    def fetch_clob_market(self, condition_id: str) -> dict[str, Any]:
        payload = self._get_json(f"{self.clob_url}/markets/{condition_id}")
        if not isinstance(payload, dict):
            raise RuntimeError(f"Unexpected clob market payload: {type(payload)}")
        return payload

    def fetch_book(self, token_id: str) -> dict[str, Any]:
        payload = self._get_json(f"{self.clob_url}/book", params={"token_id": token_id})
        if not isinstance(payload, dict):
            raise RuntimeError(f"Unexpected book payload: {type(payload)}")
        return payload

    def _split_yes_no_tokens(self, tokens: list[Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        yes: dict[str, Any] = {}
        no: dict[str, Any] = {}

        for token in tokens:
            if not isinstance(token, dict):
                continue
            outcome = str(token.get("outcome") or "").strip().lower()
            if outcome == "yes":
                yes = token
            elif outcome == "no":
                no = token

        if not yes or not no:
            raise UnsupportedMarketError(f"Unable to determine yes/no token mapping from tokens: {tokens}")

        return yes, no

    def fetch_market(self, condition_id: str) -> MarketInfo:
        gamma = self.fetch_gamma_market(condition_id) or {}
        clob = self.fetch_clob_market(condition_id)

        tokens = clob.get("tokens") or []
        yes, no = self._split_yes_no_tokens(tokens)

        title = gamma.get("question") or clob.get("question")
        slug = gamma.get("slug") or clob.get("market_slug")
        end_time = parse_datetime(gamma.get("endDate") or clob.get("end_date_iso"))
        liquidity_raw = gamma.get("liquidity")
        liquidity = float(liquidity_raw) if liquidity_raw not in (None, "") else None

        merged_raw = {"gamma": gamma, "clob": clob}

        return MarketInfo(
            condition_id=condition_id,
            title=str(title) if title is not None else None,
            slug=str(slug) if slug is not None else None,
            end_time=end_time,
            liquidity=liquidity,
            active=bool(clob.get("active", False)),
            closed=bool(clob.get("closed", False)),
            yes_token_id=str(yes.get("token_id")) if yes.get("token_id") is not None else None,
            no_token_id=str(no.get("token_id")) if no.get("token_id") is not None else None,
            yes_outcome=str(yes.get("outcome")) if yes.get("outcome") is not None else None,
            no_outcome=str(no.get("outcome")) if no.get("outcome") is not None else None,
            raw_json=merged_raw,
        )
