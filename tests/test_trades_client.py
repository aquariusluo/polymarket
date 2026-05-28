from __future__ import annotations

import pytest

from app.clients.trades_client import TradesClient


def test_fetch_recent_trades_surfaces_parse_error():
    client = TradesClient()
    client._get_json = lambda url, params: [{'transactionHash': '0xtx', 'user': '0x1'}]

    with pytest.raises(RuntimeError, match='Missing timestamp'):
        client.fetch_recent_trades('0x1')
