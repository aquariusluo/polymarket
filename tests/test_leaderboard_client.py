from __future__ import annotations

import pytest

from app.clients.leaderboard_client import LeaderboardClient


def test_fetch_build_id_supports_embedded_json_and_next_data_patterns():
    client = LeaderboardClient(base_url='https://example.com')
    client._get_text = lambda url: '<script>"buildId":"build-123"</script>'
    assert client.fetch_build_id() == 'build-123'

    client._get_text = lambda url: '<a href="/_next/data/build-456/leaderboard.json">x</a>'
    assert client.fetch_build_id() == 'build-456'


def test_extract_rows_finds_nested_leader_list_and_parse_leader_fallbacks():
    client = LeaderboardClient(base_url='https://example.com')
    payload = {
        'props': {
            'deep': {
                'rows': [
                    {
                        'proxyWallet': '0xabc',
                        'username': 'alice',
                        'profitUsd': '12.5',
                        'volumeUsd': '33.0',
                    }
                ]
            }
        }
    }

    rows = client._extract_rows(payload)
    leader = client._parse_leader(rows[0], fallback_rank=7)

    assert len(rows) == 1
    assert leader.rank == 7
    assert leader.wallet == '0xabc'
    assert leader.pseudonym == 'alice'
    assert leader.pnl_snapshot == 12.5
    assert leader.volume_snapshot == 33.0


def test_fetch_leaders_uses_extracted_rows_and_top_n_limit():
    client = LeaderboardClient(base_url='https://example.com')
    client.fetch_build_id = lambda: 'build-789'
    client._get_json = lambda url: {
        'pageProps': {
            'leaders': [
                {'wallet': '0x1', 'rank': 1},
                {'wallet': '0x2', 'rank': 2},
                {'wallet': '0x3', 'rank': 3},
            ]
        }
    }

    leaders = client.fetch_leaders(top_n=2)

    assert [leader.wallet for leader in leaders] == ['0x1', '0x2']


def test_parse_leader_raises_for_missing_wallet():
    client = LeaderboardClient(base_url='https://example.com')

    with pytest.raises(RuntimeError, match='Missing wallet'):
        client._parse_leader({'rank': 1}, fallback_rank=1)



def test_base_client_uses_bounded_redirects():
    client = LeaderboardClient(base_url='https://example.com')

    assert client.http_client.follow_redirects is True
    assert client.http_client.max_redirects == 3



def test_fetch_build_id_rejects_invalid_characters():
    client = LeaderboardClient(base_url='https://example.com')
    client._get_text = lambda url: '<script>"buildId":"../bad"</script>'

    with pytest.raises(RuntimeError, match='Invalid buildId'):
        client.fetch_build_id()
