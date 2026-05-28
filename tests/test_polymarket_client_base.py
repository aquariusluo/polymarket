from __future__ import annotations

import httpx

from app.clients.base_client import BasePolymarketClient


class DummyClient(BasePolymarketClient):
    pass


def test_base_client_reuses_injected_http_client_for_multiple_requests():
    calls: list[tuple[str, str, dict | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url), dict(request.headers)))
        if request.url.path.endswith('/text'):
            return httpx.Response(200, text='ok')
        return httpx.Response(200, json={'ok': True})

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    client = DummyClient(base_url='https://example.com/api', http_client=http_client)

    assert client._get_json('https://example.com/api/json') == {'ok': True}
    assert client._get_text('https://example.com/api/text') == 'ok'
    assert len(calls) == 2
    assert all(headers.get('user-agent') == 'Mozilla/5.0 (compatible; polymarket-copytrader/0.1)' for _, _, headers in calls)
    assert client.http_client is http_client
