from datetime import datetime, timedelta, timezone
import inspect

from app.config import Settings
from app.domain.filters import TradeFilter
from app.domain.models import Decision, LeaderTrade, MarketInfo, Side


def make_settings() -> Settings:
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


def make_filter() -> TradeFilter:
    settings = make_settings()
    return TradeFilter(
        min_market_liquidity=settings.min_market_liquidity,
        min_time_to_expiry_hours=settings.min_time_to_expiry_hours,
        max_trade_age_minutes=settings.max_trade_age_minutes,
    )


def make_trade(side='BUY', asset_id='yes-token', condition_id='cond1'):
    return LeaderTrade(
        wallet='0x1',
        leader_name='alice',
        transaction_hash='0xtx',
        condition_id=condition_id,
        asset_id=asset_id,
        side=side,
        size=10.0,
        price=0.55,
        timestamp=datetime.now(timezone.utc),
        market_title='Test',
        market_slug='test-market',
        raw_json={},
    )


def make_market(liquidity=20000, hours=48, yes='yes-token', no='no-token', active=True, closed=False):
    return MarketInfo(
        condition_id='cond1',
        title='Test',
        slug='test-market',
        end_time=datetime.now(timezone.utc) + timedelta(hours=hours),
        liquidity=liquidity,
        active=active,
        closed=closed,
        yes_token_id=yes,
        no_token_id=no,
        yes_outcome='Yes',
        no_outcome='No',
        raw_json={},
    )


def test_trade_filter_constructor_uses_threshold_values_not_settings():
    params = list(inspect.signature(TradeFilter).parameters)
    assert params == ['min_market_liquidity', 'min_time_to_expiry_hours', 'max_trade_age_minutes']


def test_filter_accepts_valid_buy_trade():
    decision = make_filter().evaluate(1, make_trade(), make_market())
    assert decision.decision == 'accepted'


def test_filter_rejects_sell_trade():
    decision = make_filter().evaluate(1, make_trade(side='SELL'), make_market())
    assert decision.reason == 'side_not_buy'


def test_filter_rejects_low_liquidity():
    decision = make_filter().evaluate(1, make_trade(), make_market(liquidity=500))
    assert decision.reason == 'liquidity_below_threshold'


def test_filter_rejects_missing_condition_id():
    decision = make_filter().evaluate(1, make_trade(condition_id=None), make_market())
    assert decision.reason == 'missing_condition_id'


def test_filter_rejects_market_not_found():
    decision = make_filter().evaluate(1, make_trade(), None)
    assert decision.reason == 'market_not_found'


def test_filter_rejects_inactive_or_closed_market():
    decision_inactive = make_filter().evaluate(1, make_trade(), make_market(active=False, closed=False))
    assert decision_inactive.reason == 'market_inactive_or_closed'
    decision_closed = make_filter().evaluate(1, make_trade(), make_market(active=True, closed=True))
    assert decision_closed.reason == 'market_inactive_or_closed'


def test_filter_rejects_market_too_close_to_expiry():
    decision = make_filter().evaluate(1, make_trade(), make_market(hours=1))
    assert decision.reason == 'too_close_to_expiry'


def test_filter_rejects_asset_not_in_market_tokens():
    decision = make_filter().evaluate(1, make_trade(asset_id='other-token'), make_market())
    assert decision.reason == 'asset_not_in_market_tokens'


def test_filter_rejects_stale_trade():
    stale_trade = make_trade()
    stale_trade.timestamp = datetime.now(timezone.utc) - timedelta(hours=5)
    decision = make_filter().evaluate(1, stale_trade, make_market())
    assert decision.reason == 'trade_too_old'


def test_filter_rejects_future_dated_trade():
    future_trade = make_trade()
    future_trade.timestamp = datetime.now(timezone.utc) + timedelta(minutes=10)
    decision = make_filter().evaluate(1, future_trade, make_market())
    assert decision.reason == 'trade_timestamp_in_future'



def test_filter_returns_enum_backed_decision_and_side():
    decision = make_filter().evaluate(1, make_trade(side='BUY'), make_market())

    assert isinstance(decision.decision, Decision)
    assert decision.decision is Decision.ACCEPTED
    assert decision.side is Side.BUY
