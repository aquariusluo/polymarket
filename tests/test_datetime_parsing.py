from __future__ import annotations

from datetime import timezone

from app.clients.market_client import MarketClient
from app.clients.trades_client import TradesClient
from app.domain.models import LeaderTrade, parse_datetime


class StubMarketClient(MarketClient):
    def __init__(self):
        super().__init__(gamma_url='https://example.com', clob_url='https://example.com')

    def fetch_gamma_market(self, condition_id: str):
        return {'question': 'Will X happen?', 'slug': 'will-x-happen', 'endDate': '2030-01-01T00:00:00', 'liquidity': '12345'}

    def fetch_clob_market(self, condition_id: str):
        return {
            'question': 'Will X happen?',
            'market_slug': 'will-x-happen',
            'end_date_iso': '2030-01-01T00:00:00Z',
            'active': True,
            'closed': False,
            'tokens': [
                {'token_id': 'token-no', 'outcome': 'No'},
                {'token_id': 'token-yes', 'outcome': 'Yes'},
            ],
        }


def test_parse_datetime_normalizes_zulu_and_epoch_inputs():
    assert parse_datetime('2030-01-01T00:00:00Z').tzinfo == timezone.utc
    assert parse_datetime('1716688800').tzinfo == timezone.utc
    assert parse_datetime(1716688800).tzinfo == timezone.utc


def test_leader_trade_from_row_uses_shared_datetime_parser_for_naive_iso():
    trade = LeaderTrade.from_row({
        'wallet': '0x1',
        'leader_name': 'alice',
        'transaction_hash': '0xtx',
        'condition_id': 'cond1',
        'asset_id': 'asset_yes',
        'side': 'BUY',
        'size': 10.0,
        'price': 0.55,
        'timestamp': '2030-01-01T00:00:00',
        'market_title': 'Will X happen?',
        'market_slug': 'will-x-happen',
        'raw_json': {},
    })

    assert trade.timestamp.tzinfo == timezone.utc


def test_market_and_trades_clients_use_shared_datetime_parser():
    market = StubMarketClient().fetch_market('cond1')
    trade = TradesClient()._parse_trade({
        'transactionHash': '0xtx',
        'user': '0x1',
        'timestamp': '2030-01-01T00:00:00',
        'conditionId': 'cond1',
        'assetId': 'asset_yes',
        'side': 'BUY',
        'size': '10',
        'price': '0.55',
        'title': 'Will X happen?',
        'slug': 'will-x-happen',
    }, leader_name='alice')

    assert market.end_time is not None
    assert market.end_time.tzinfo == timezone.utc
    assert trade.timestamp.tzinfo == timezone.utc
