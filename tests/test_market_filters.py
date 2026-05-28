from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.domain.filters import TradeFilter
from app.domain.models import LeaderTrade, MarketInfo


def _settings() -> Settings:
    return Settings(
        app_env='test',
        db_path=':memory:',
        leaderboard_category='overall',
        leaderboard_time='30d',
        leaderboard_sort='profit',
        top_n=5,
        poll_interval_seconds=10,
        trade_fetch_limit=50,
        min_time_to_expiry_hours=24,
        min_market_liquidity=10000,
        signal_cooldown_minutes=5,
    )


def _filter() -> TradeFilter:
    settings = _settings()
    return TradeFilter(
        min_market_liquidity=settings.min_market_liquidity,
        min_time_to_expiry_hours=settings.min_time_to_expiry_hours,
        max_trade_age_minutes=settings.max_trade_age_minutes,
    )


def _trade(**overrides):
    base = LeaderTrade(
        wallet='0x1',
        leader_name='alice',
        transaction_hash='0xtx',
        condition_id='cond1',
        asset_id='asset_yes',
        side='BUY',
        size=12.0,
        price=0.55,
        timestamp=datetime.now(timezone.utc),
        market_title='Will X happen?',
        market_slug='will-x-happen',
        raw_json={},
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _market(**overrides):
    base = MarketInfo(
        condition_id='cond1',
        slug='will-x-happen',
        title='Will X happen?',
        end_time=datetime.now(timezone.utc) + timedelta(days=3),
        liquidity=25000.0,
        active=True,
        closed=False,
        yes_token_id='asset_yes',
        no_token_id='asset_no',
        yes_outcome='Yes',
        no_outcome='No',
        raw_json={},
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def test_filter_accepts_normal_buy_trade():
    decision = _filter().evaluate(1, _trade(), _market())
    assert decision.decision == 'accepted'
    assert decision.reason == 'accepted'


def test_filter_rejects_low_liquidity_market():
    decision = _filter().evaluate(1, _trade(), _market(liquidity=5000.0))
    assert decision.decision == 'rejected'
    assert decision.reason == 'liquidity_below_threshold'
