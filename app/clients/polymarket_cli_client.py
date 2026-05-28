from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from typing import Any

from app.domain.models import Leader, LeaderTrade, parse_datetime

CliRunner = Callable[[list[str]], str]
_EVM_ADDRESS_RE = re.compile(r'^0x[a-fA-F0-9]{40}$')


def _run_cli(args: list[str], timeout_seconds: float) -> str:
    completed = subprocess.run(
        args,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    return completed.stdout


class PolymarketCliError(RuntimeError):
    pass


class PolymarketCliBase:
    def __init__(
        self,
        executable: str = 'polymarket',
        runner: CliRunner | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.executable = executable
        self._runner = runner or (lambda args: _run_cli(args, timeout_seconds))

    def _json(self, *args: str) -> Any:
        command = [self.executable, '-o', 'json', *args]
        try:
            output = self._runner(command)
            return json.loads(output)
        except FileNotFoundError as exc:
            raise PolymarketCliError(f'polymarket CLI executable not found: {self.executable}') from exc
        except subprocess.TimeoutExpired as exc:
            raise PolymarketCliError(f"polymarket CLI timed out: {' '.join(command)}") from exc
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip() if exc.stderr else ''
            raise PolymarketCliError(f"polymarket CLI failed: {' '.join(command)} {stderr}") from exc
        except json.JSONDecodeError as exc:
            raise PolymarketCliError(f"polymarket CLI returned invalid JSON: {' '.join(command)}") from exc


class PolymarketCliLeaderboardClient(PolymarketCliBase):
    _PERIOD_MAP = {
        '1d': 'day',
        'day': 'day',
        '7d': 'week',
        'week': 'week',
        '30d': 'month',
        'month': 'month',
        'all': 'all',
        'overall': 'all',
    }
    _ORDER_MAP = {
        'profit': 'pnl',
        'pnl': 'pnl',
        'volume': 'vol',
        'vol': 'vol',
    }

    def _parse_leader(self, row: dict[str, Any], fallback_rank: int) -> Leader:
        wallet = row.get('proxy_wallet') or row.get('proxyWallet') or row.get('wallet') or row.get('address')
        if not wallet:
            raise PolymarketCliError(f'Missing wallet in CLI leaderboard row: {row}')

        pseudonym = row.get('user_name') or row.get('username') or row.get('pseudonym')
        pnl = row.get('pnl')
        volume = row.get('volume')

        return Leader(
            rank=int(row.get('rank') or fallback_rank),
            wallet=str(wallet),
            name=None,
            pseudonym=str(pseudonym) if pseudonym is not None else None,
            pnl_snapshot=float(pnl) if pnl is not None else None,
            volume_snapshot=float(volume) if volume is not None else None,
            raw_json=row,
        )

    def fetch_leaders(
        self,
        category: str = 'overall',
        time_window: str = '30d',
        sort: str = 'profit',
        top_n: int = 5,
    ) -> list[Leader]:
        del category  # The CLI leaderboard currently exposes period/order only.
        period = self._PERIOD_MAP.get(time_window, time_window)
        order_by = self._ORDER_MAP.get(sort, sort)
        payload = self._json(
            'data',
            'leaderboard',
            '--period',
            period,
            '--order-by',
            order_by,
            '--limit',
            str(top_n),
        )
        if not isinstance(payload, list):
            raise PolymarketCliError(f'Unexpected CLI leaderboard payload type: {type(payload)}')

        leaders: list[Leader] = []
        for i, row in enumerate(payload[:top_n], start=1):
            if not isinstance(row, dict):
                raise PolymarketCliError(f'Unexpected CLI leaderboard row type: {type(row)}')
            leaders.append(self._parse_leader(row, fallback_rank=i))
        return leaders


class PolymarketCliTradesClient(PolymarketCliBase):
    def __init__(
        self,
        executable: str = 'polymarket',
        runner: CliRunner | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        super().__init__(executable=executable, runner=runner, timeout_seconds=timeout_seconds)
        self._market_cache: dict[str, dict[str, Any]] = {}

    def _market(self, condition_id: str) -> dict[str, Any]:
        cached = self._market_cache.get(condition_id)
        if cached is not None:
            return cached
        payload = self._json('clob', 'market', condition_id)
        if not isinstance(payload, dict):
            raise PolymarketCliError(f'Unexpected CLI market payload type: {type(payload)}')
        self._market_cache[condition_id] = payload
        return payload

    def _asset_id_for_outcome(self, row: dict[str, Any]) -> str:
        asset_id = row.get('assetId') or row.get('asset_id') or row.get('asset')
        if asset_id is not None:
            return str(asset_id)

        condition_id = row.get('condition_id') or row.get('conditionId')
        outcome = row.get('outcome')
        if not condition_id or outcome is None:
            raise PolymarketCliError(f'Missing asset_id and outcome lookup fields in CLI trade row: {row}')

        market = self._market(str(condition_id))
        tokens = market.get('tokens')
        if not isinstance(tokens, list):
            raise PolymarketCliError(f'Missing tokens in CLI market payload for {condition_id}')

        expected = str(outcome).strip().casefold()
        exact_matches: list[str] = []
        folded_matches: list[str] = []
        for token in tokens:
            if not isinstance(token, dict):
                continue
            token_outcome = token.get('outcome')
            token_id = token.get('token_id') or token.get('tokenId')
            if token_outcome is None or token_id is None:
                continue
            token_outcome_text = str(token_outcome).strip()
            if token_outcome_text == str(outcome).strip():
                exact_matches.append(str(token_id))
            elif token_outcome_text.casefold() == expected:
                folded_matches.append(str(token_id))

        if len(exact_matches) == 1:
            return exact_matches[0]
        if len(folded_matches) == 1 and not exact_matches:
            return folded_matches[0]

        raise PolymarketCliError(f'Could not resolve asset_id for outcome {outcome!r} in market {condition_id}')

    def _parse_trade(self, row: dict[str, Any], leader_name: str | None) -> LeaderTrade:
        tx_hash = row.get('transaction_hash') or row.get('transactionHash') or row.get('txHash')
        if not tx_hash:
            raise PolymarketCliError(f'Missing transaction hash in CLI trade row: {row}')

        wallet = row.get('proxy_wallet') or row.get('proxyWallet') or row.get('wallet') or row.get('user')
        if not wallet:
            raise PolymarketCliError(f'Missing wallet in CLI trade row: {row}')

        timestamp = row.get('timestamp') or row.get('createdAt') or row.get('time')
        parsed_timestamp = parse_datetime(timestamp)
        if parsed_timestamp is None:
            raise PolymarketCliError(f'Missing timestamp in CLI trade row: {row}')

        condition_id = row.get('condition_id') or row.get('conditionId')

        return LeaderTrade(
            wallet=str(wallet),
            leader_name=leader_name,
            transaction_hash=str(tx_hash),
            condition_id=str(condition_id) if condition_id is not None else None,
            asset_id=self._asset_id_for_outcome(row),
            side=str(row.get('side')) if row.get('side') is not None else None,
            size=float(row['size']) if row.get('size') is not None else None,
            price=float(row['price']) if row.get('price') is not None else None,
            timestamp=parsed_timestamp,
            market_title=str(row.get('title') or row.get('marketTitle')) if (row.get('title') or row.get('marketTitle')) is not None else None,
            market_slug=str(row.get('slug') or row.get('marketSlug')) if (row.get('slug') or row.get('marketSlug')) is not None else None,
            raw_json=row,
        )

    def fetch_recent_trades(
        self,
        wallet: str,
        limit: int = 50,
        leader_name: str | None = None,
    ) -> list[LeaderTrade]:
        if not _EVM_ADDRESS_RE.fullmatch(wallet):
            raise PolymarketCliError(f'Invalid EVM wallet address for CLI trades lookup: {wallet}')
        payload = self._json('data', 'trades', wallet, '--limit', str(limit))
        if not isinstance(payload, list):
            raise PolymarketCliError(f'Unexpected CLI trades payload type: {type(payload)}')

        trades: list[LeaderTrade] = []
        for row in payload:
            if not isinstance(row, dict):
                raise PolymarketCliError(f'Unexpected CLI trade row type: {type(row)}')
            trades.append(self._parse_trade(row, leader_name=leader_name))
        return trades
