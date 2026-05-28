from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.clients.base_client import BasePolymarketClient
from app.domain.models import Leader

_BUILD_ID_RE = re.compile(r'^[A-Za-z0-9_-]+$')


class LeaderboardClient(BasePolymarketClient):
    def __init__(
        self,
        base_url: str = "https://polymarket.com",
        timeout: float = 20.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        super().__init__(base_url=base_url, timeout=timeout, http_client=http_client)

    def _validate_build_id(self, build_id: str) -> str:
        if not _BUILD_ID_RE.fullmatch(build_id):
            raise RuntimeError(f'Invalid buildId extracted from leaderboard HTML: {build_id}')
        return build_id

    def fetch_build_id(self) -> str:
        html = self._get_text(f"{self.base_url}/leaderboard")

        patterns = [
            r'"buildId":"([^"]+)"',
            r'/_next/data/([^/]+)/leaderboard\.json',
        ]
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                return self._validate_build_id(match.group(1))

        raise RuntimeError("Could not extract buildId from leaderboard HTML")

    def _looks_like_leader_rows(self, rows: list[Any]) -> bool:
        if not rows or not isinstance(rows[0], dict):
            return False
        sample = rows[0]
        keys = set(sample.keys())
        return bool({"wallet", "address", "proxyWallet", "userAddress"} & keys)

    def _extract_rows(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list) and self._looks_like_leader_rows(payload):
            return payload

        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected leaderboard payload type")

        candidates = [
            payload.get("pageProps", {}).get("leaders"),
            payload.get("pageProps", {}).get("leaderboard"),
            payload.get("pageProps", {}).get("rows"),
            payload.get("leaders"),
            payload.get("leaderboard"),
            payload.get("rows"),
        ]

        for item in candidates:
            if isinstance(item, list) and self._looks_like_leader_rows(item):
                return item

        def _find_list(obj: Any) -> list[dict[str, Any]] | None:
            if isinstance(obj, list):
                if self._looks_like_leader_rows(obj):
                    return obj
                for item in obj:
                    found = _find_list(item)
                    if found is not None:
                        return found
            if isinstance(obj, dict):
                for value in obj.values():
                    found = _find_list(value)
                    if found is not None:
                        return found
            return None

        found = _find_list(payload)
        if found is not None:
            return found

        raise RuntimeError("Could not locate leaderboard rows in payload")

    def _parse_leader(self, row: dict[str, Any], fallback_rank: int) -> Leader:
        wallet = (
            row.get("wallet")
            or row.get("address")
            or row.get("proxyWallet")
            or row.get("userAddress")
        )
        if not wallet:
            raise RuntimeError(f"Missing wallet in leaderboard row: {json.dumps(row)[:300]}")

        rank = row.get("rank") or fallback_rank
        name = row.get("name")
        pseudonym = row.get("pseudonym") or row.get("username") or row.get("handle")
        pnl = row.get("profit") or row.get("pnl") or row.get("profitUsd")
        volume = row.get("volume") or row.get("volumeUsd")

        return Leader(
            rank=int(rank),
            wallet=str(wallet),
            name=str(name) if name is not None else None,
            pseudonym=str(pseudonym) if pseudonym is not None else None,
            pnl_snapshot=float(pnl) if pnl is not None else None,
            volume_snapshot=float(volume) if volume is not None else None,
            raw_json=row,
        )

    def fetch_leaders(
        self,
        category: str = "overall",
        time_window: str = "30d",
        sort: str = "profit",
        top_n: int = 5,
    ) -> list[Leader]:
        build_id = self.fetch_build_id()
        url = (
            f"{self.base_url}/_next/data/{build_id}/leaderboard.json"
            f"?category={category}&time={time_window}&sort={sort}"
        )
        payload = self._get_json(url)
        rows = self._extract_rows(payload)

        leaders: list[Leader] = []
        for i, row in enumerate(rows[:top_n], start=1):
            leaders.append(self._parse_leader(row, fallback_rank=i))

        return leaders
