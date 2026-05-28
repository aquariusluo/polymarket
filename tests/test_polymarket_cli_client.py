from __future__ import annotations

import json
import subprocess
from datetime import timezone

import pytest

from app.clients.polymarket_cli_client import PolymarketCliError
from app.clients.polymarket_cli_client import PolymarketCliLeaderboardClient, PolymarketCliTradesClient

VALID_WALLET = '0x1111111111111111111111111111111111111111'


def test_cli_leaderboard_parses_rows_and_maps_options():
    calls: list[list[str]] = []

    def runner(args: list[str]) -> str:
        calls.append(args)
        return json.dumps([
            {
                'rank': 1,
                'proxy_wallet': '0xleader',
                'user_name': 'leader-one',
                'pnl': '123.45',
                'volume': '987.65',
            },
        ])

    client = PolymarketCliLeaderboardClient(runner=runner)

    leaders = client.fetch_leaders(time_window='30d', sort='profit', top_n=1)

    assert calls == [[
        'polymarket',
        '-o',
        'json',
        'data',
        'leaderboard',
        '--period',
        'month',
        '--order-by',
        'pnl',
        '--limit',
        '1',
    ]]
    assert leaders[0].wallet == '0xleader'
    assert leaders[0].pseudonym == 'leader-one'
    assert leaders[0].pnl_snapshot == 123.45
    assert leaders[0].volume_snapshot == 987.65


def test_cli_trades_resolves_asset_id_from_clob_market():
    calls: list[list[str]] = []

    def runner(args: list[str]) -> str:
        calls.append(args)
        if args[3:5] == ['data', 'trades']:
            return json.dumps([
                {
                    'condition_id': '0xcondition',
                    'outcome': 'Yes',
                    'price': '0.42',
                    'proxy_wallet': VALID_WALLET,
                    'side': 'BUY',
                    'size': '10',
                    'slug': 'test-market',
                    'timestamp': 1779827302,
                    'title': 'Test market',
                    'transaction_hash': '0xtx',
                },
            ])
        if args[3:5] == ['clob', 'market']:
            return json.dumps({
                'tokens': [
                    {'token_id': 'asset-yes', 'outcome': 'Yes'},
                    {'token_id': 'asset-no', 'outcome': 'No'},
                ],
            })
        raise AssertionError(f'unexpected command: {args}')

    client = PolymarketCliTradesClient(runner=runner)

    trades = client.fetch_recent_trades(VALID_WALLET, limit=1, leader_name='leader-one')

    assert calls == [
        ['polymarket', '-o', 'json', 'data', 'trades', VALID_WALLET, '--limit', '1'],
        ['polymarket', '-o', 'json', 'clob', 'market', '0xcondition'],
    ]
    assert trades[0].asset_id == 'asset-yes'
    assert trades[0].leader_name == 'leader-one'
    assert trades[0].condition_id == '0xcondition'
    assert trades[0].market_slug == 'test-market'
    assert trades[0].timestamp.tzinfo == timezone.utc


def test_cli_trades_rejects_invalid_wallet_before_running_command():
    calls: list[list[str]] = []
    client = PolymarketCliTradesClient(runner=lambda args: calls.append(args) or '[]')

    with pytest.raises(PolymarketCliError, match='Invalid EVM wallet'):
        client.fetch_recent_trades('not-a-wallet')

    assert calls == []


def test_cli_errors_wrap_subprocess_failures():
    def runner(args: list[str]) -> str:
        raise subprocess.CalledProcessError(returncode=1, cmd=args, stderr='boom')

    client = PolymarketCliLeaderboardClient(runner=runner)

    with pytest.raises(PolymarketCliError, match='polymarket CLI failed'):
        client.fetch_leaders()
