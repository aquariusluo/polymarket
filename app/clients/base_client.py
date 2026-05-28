from __future__ import annotations

from typing import Any

import httpx


class BasePolymarketClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout: float = 20.0,
        max_redirects: int = 3,
        headers: dict[str, str] | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.max_redirects = max_redirects
        self.headers = headers or {
            'User-Agent': 'Mozilla/5.0 (compatible; polymarket-copytrader/0.1)'
        }
        if http_client is None:
            self.http_client = httpx.Client(
                timeout=self.timeout,
                follow_redirects=True,
                max_redirects=self.max_redirects,
                headers=self.headers,
            )
        else:
            http_client.headers.update(self.headers)
            self.http_client = http_client

    def _get_text(self, url: str, params: dict[str, Any] | None = None) -> str:
        response = self.http_client.get(url, params=params)
        response.raise_for_status()
        return response.text

    def _get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        response = self.http_client.get(url, params=params)
        response.raise_for_status()
        return response.json()
