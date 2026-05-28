from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Decision(str, Enum):
    ACCEPTED = 'accepted'
    REJECTED = 'rejected'


class Side(str, Enum):
    BUY = 'BUY'
    SELL = 'SELL'



def normalize_side(value: Any) -> Side | None:
    if value in (None, ''):
        return None
    text = str(value).upper()
    try:
        return Side(text)
    except ValueError:
        return None



def parse_datetime(value: Any) -> datetime | None:
    if value in (None, ''):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        parsed = datetime.fromtimestamp(value, tz=timezone.utc)
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.isdigit():
            parsed = datetime.fromtimestamp(int(text), tz=timezone.utc)
        else:
            parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass
class Leader:
    rank: int
    wallet: str
    name: str | None
    pseudonym: str | None
    pnl_snapshot: float | None
    volume_snapshot: float | None
    selection_run_id: str | None = None
    raw_json: dict[str, Any] | None = None


@dataclass
class LeaderTrade:
    wallet: str
    leader_name: str | None
    transaction_hash: str
    condition_id: str | None
    asset_id: str
    side: str | None
    size: float | None
    price: float | None
    timestamp: datetime
    market_title: str | None
    market_slug: str | None
    raw_json: dict[str, Any]

    @classmethod
    def from_row(cls, row: Any) -> "LeaderTrade":
        timestamp = parse_datetime(row['timestamp'])
        if timestamp is None:
            raise RuntimeError('missing timestamp in leader trade row')
        raw_json = row['raw_json']
        if not isinstance(raw_json, dict):
            raw_json = json.loads(raw_json) if raw_json else {}
        return cls(
            wallet=str(row['wallet']),
            leader_name=row['leader_name'],
            transaction_hash=str(row['transaction_hash']),
            condition_id=str(row['condition_id']) if row['condition_id'] is not None else None,
            asset_id=str(row['asset_id']),
            side=row['side'],
            size=float(row['size']) if row['size'] is not None else None,
            price=float(row['price']) if row['price'] is not None else None,
            timestamp=timestamp,
            market_title=row['market_title'],
            market_slug=row['market_slug'],
            raw_json=raw_json,
        )


@dataclass
class MarketInfo:
    condition_id: str
    title: str | None
    slug: str | None
    end_time: datetime | None
    liquidity: float | None
    active: bool
    closed: bool
    yes_token_id: str | None
    no_token_id: str | None
    yes_outcome: str | None
    no_outcome: str | None
    raw_json: dict[str, Any]
    refreshed_at: datetime | None = None


@dataclass
class SignalDecision:
    leader_trade_id: int
    condition_id: str
    asset_id: str
    decision: Decision
    reason: str
    side: Side | None
    price: float | None
    market_slug: str | None
