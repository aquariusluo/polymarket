from __future__ import annotations

import pytest

from app.clients.market_client import MarketClient


class StubMarketClient(MarketClient):
    def __init__(self):
        super().__init__(gamma_url="https://example.com", clob_url="https://example.com")

    def fetch_gamma_market(self, condition_id: str):
        return {
            "question": "Will X happen?",
            "slug": "will-x-happen",
            "endDate": "2030-01-01T00:00:00Z",
            "liquidity": "12345",
        }

    def fetch_clob_market(self, condition_id: str):
        return {
            "question": "Will X happen?",
            "market_slug": "will-x-happen",
            "active": True,
            "closed": False,
            "tokens": [
                {"token_id": "token-no", "outcome": "No"},
                {"token_id": "token-yes", "outcome": "Yes"},
            ],
        }


class UnlabeledTokenMarketClient(StubMarketClient):
    def fetch_clob_market(self, condition_id: str):
        return {
            "question": "Will X happen?",
            "market_slug": "will-x-happen",
            "active": True,
            "closed": False,
            "tokens": [
                {"token_id": "token-a"},
                {"token_id": "token-b"},
            ],
        }


def test_fetch_market_maps_yes_no_tokens_by_outcome_label():
    market = StubMarketClient().fetch_market("cond1")

    assert market.yes_token_id == "token-yes"
    assert market.no_token_id == "token-no"
    assert market.yes_outcome == "Yes"
    assert market.no_outcome == "No"


def test_fetch_market_rejects_unlabeled_binary_tokens():
    with pytest.raises(RuntimeError, match='Unable to determine yes/no token mapping'):
        UnlabeledTokenMarketClient().fetch_market('cond1')
