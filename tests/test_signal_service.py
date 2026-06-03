from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.domain.models import MarketInfo, MISSING_CONDITION_ID
from app.services.signal_service import SignalService
from app.storage.db import get_connection, init_db


class DummyBookClient:
    def __init__(self, asks=None, bids=None, should_raise: bool = False):
        self.asks = asks or [{'price': 0.58, 'size': 500.0}]
        self.bids = bids or [{'price': 0.57, 'size': 500.0}]
        self.should_raise = should_raise

    def fetch_book(self, token_id: str):
        if self.should_raise:
            raise httpx.ReadTimeout('book timeout')
        return {
            'asks': self.asks,
            'bids': self.bids,
        }


class DummyMarketService:
    def __init__(self, market_info: MarketInfo, book_client: DummyBookClient | None = None):
        self.market_info = market_info
        self.market_client = book_client or DummyBookClient()

    def get_market(self, condition_id: str) -> MarketInfo | None:
        if condition_id == self.market_info.condition_id:
            return self.market_info
        return None


class RaisingMarketService:
    def get_market(self, condition_id: str) -> MarketInfo | None:
        raise RuntimeError('upstream market failure')


class UnsupportedMarketService:
    def get_market(self, condition_id: str) -> MarketInfo | None:
        from app.clients.market_client import UnsupportedMarketError

        raise UnsupportedMarketError('multi-outcome market not supported')


class TimeoutMarketService:
    def get_market(self, condition_id: str) -> MarketInfo | None:
        raise httpx.ReadTimeout('upstream timeout')


def _settings(db_path: str) -> Settings:
    return Settings(
        app_env='test',
        db_path=db_path,
        leaderboard_category='overall',
        leaderboard_time='30d',
        leaderboard_sort='profit',
        top_n=5,
        poll_interval_seconds=10,
        trade_fetch_limit=50,
        min_time_to_expiry_hours=24,
        min_market_liquidity=10000,
        signal_cooldown_minutes=5,
        max_signal_age_minutes=15,
    )


def _settings_with_excluded_wallet(db_path: str, wallet: str) -> Settings:
    return Settings(
        app_env='test',
        db_path=db_path,
        leaderboard_category='overall',
        leaderboard_time='30d',
        leaderboard_sort='profit',
        top_n=5,
        poll_interval_seconds=10,
        trade_fetch_limit=50,
        min_time_to_expiry_hours=24,
        min_market_liquidity=10000,
        signal_cooldown_minutes=5,
        max_signal_age_minutes=15,
        scarf_excluded_wallets=(wallet,),
    )


def test_signal_service_creates_signal_for_accepted_trade(tmp_path: Path):
    db_path = tmp_path / 'test.db'
    init_db(str(db_path))

    market = MarketInfo(
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

    with get_connection(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO leader_trades (
                wallet, leader_name, transaction_hash, condition_id, asset_id, side,
                size, price, timestamp, market_title, market_slug, raw_json, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                '0x1', 'alice', '0xtx', 'cond1', 'asset_yes', 'BUY',
                10.0, 0.57, datetime.now(timezone.utc).isoformat(),
                'Will X happen?', 'will-x-happen', '{}', datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()

        result = SignalService(conn, _settings(str(db_path)), DummyMarketService(market)).run()
        assert result.processed_count == 1
        assert result.accepted_count == 1

        row = conn.execute('SELECT * FROM signals').fetchone()
        assert row is not None
        assert row['decision'] == 'accepted'
        payload = json.loads(row['raw_json'])
        assert payload['signal_evidence']['stage'] == 'copyability'
        assert payload['signal_evidence']['category'] == 'accepted'
        assert payload['signal_evidence']['decision'] == 'accepted'
        assert payload['signal_evidence']['reason'] is None
        assert payload['copyability']['best_ask_price'] == 0.58
        assert payload['copyability']['best_bid_price'] == 0.57
        assert payload['copyability']['reason'] is None


def test_signal_service_rejects_trade_when_current_book_is_not_copyable(tmp_path: Path):
    db_path = tmp_path / 'book-slippage.db'
    init_db(str(db_path))

    market = MarketInfo(
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

    with get_connection(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO leader_trades (
                wallet, leader_name, transaction_hash, condition_id, asset_id, side,
                size, price, timestamp, market_title, market_slug, raw_json, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                '0x1', 'alice', '0xtx', 'cond1', 'asset_yes', 'BUY',
                10.0, 0.57, datetime.now(timezone.utc).isoformat(),
                'Will X happen?', 'will-x-happen', '{}', datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()

        result = SignalService(
            conn,
            _settings(str(db_path)),
            DummyMarketService(market, book_client=DummyBookClient(asks=[{'price': 0.90, 'size': 500.0}])),
        ).run()

        assert result.processed_count == 1
        assert result.accepted_count == 0
        assert result.rejected_count == 1

        row = conn.execute('SELECT raw_json, decision, reason FROM signals').fetchone()
        assert row is not None
        assert row['decision'] == 'rejected'
        assert row['reason'] == 'book_spread_too_wide'
        payload = json.loads(row['raw_json'])
        assert payload['signal_evidence']['stage'] == 'copyability'
        assert payload['signal_evidence']['category'] == 'copyability'
        assert payload['signal_evidence']['reason'] == 'book_spread_too_wide'


def test_signal_service_rejects_trade_when_book_spread_is_too_wide(tmp_path: Path):
    db_path = tmp_path / 'book-spread.db'
    init_db(str(db_path))

    market = MarketInfo(
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

    with get_connection(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO leader_trades (
                wallet, leader_name, transaction_hash, condition_id, asset_id, side,
                size, price, timestamp, market_title, market_slug, raw_json, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                '0x1', 'alice', '0xtx', 'cond1', 'asset_yes', 'BUY',
                10.0, 0.98, datetime.now(timezone.utc).isoformat(),
                'Will X happen?', 'will-x-happen', '{}', datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()

        result = SignalService(
            conn,
            _settings(str(db_path)),
            DummyMarketService(
                market,
                book_client=DummyBookClient(
                    asks=[{'price': 0.99, 'size': 500.0}],
                    bids=[{'price': 0.01, 'size': 500.0}],
                ),
            ),
        ).run()

        assert result.processed_count == 1
        assert result.accepted_count == 0
        assert result.rejected_count == 1

        row = conn.execute('SELECT raw_json, decision, reason FROM signals').fetchone()
        assert row is not None
        assert row['decision'] == 'rejected'
        assert row['reason'] == 'book_spread_too_wide'
        payload = json.loads(row['raw_json'])
        assert payload['signal_evidence']['stage'] == 'copyability'
        assert payload['signal_evidence']['category'] == 'copyability'
        assert payload['signal_evidence']['reason'] == 'book_spread_too_wide'


def test_signal_service_surfaces_market_lookup_failure(tmp_path: Path):
    db_path = tmp_path / 'market-failure.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO leader_trades (
                wallet, leader_name, transaction_hash, condition_id, asset_id, side,
                size, price, timestamp, market_title, market_slug, raw_json, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                '0x1', 'alice', '0xtx', 'cond1', 'asset_yes', 'BUY',
                10.0, 0.57, datetime.now(timezone.utc).isoformat(),
                'Will X happen?', 'will-x-happen', '{}', datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()

        with pytest.raises(RuntimeError, match='upstream market failure'):
            SignalService(conn, _settings(str(db_path)), RaisingMarketService()).run()


def test_signal_service_rejects_unsupported_market_without_crashing(tmp_path: Path):
    db_path = tmp_path / 'unsupported-market.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO leader_trades (
                wallet, leader_name, transaction_hash, condition_id, asset_id, side,
                size, price, timestamp, market_title, market_slug, raw_json, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                '0x1', 'alice', '0xtx', 'cond1', 'asset_yes', 'BUY',
                10.0, 0.57, datetime.now(timezone.utc).isoformat(),
                'Will X happen?', 'will-x-happen', '{}', datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()

        result = SignalService(conn, _settings(str(db_path)), UnsupportedMarketService()).run()

        assert result.processed_count == 1
        assert result.rejected_count == 1
        row = conn.execute('SELECT raw_json, decision, reason FROM signals').fetchone()
        assert row['decision'] == 'rejected'
        assert row['reason'] == 'market_unsupported'
        payload = json.loads(row['raw_json'])
        assert payload['signal_evidence']['stage'] == 'market_lookup'
        assert payload['signal_evidence']['category'] == 'market_lookup'
        assert payload['signal_evidence']['reason'] == 'market_unsupported'


def test_signal_service_rejects_market_timeout_without_crashing(tmp_path: Path):
    db_path = tmp_path / 'timeout-market.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO leader_trades (
                wallet, leader_name, transaction_hash, condition_id, asset_id, side,
                size, price, timestamp, market_title, market_slug, raw_json, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                '0x1', 'alice', '0xtx', 'cond1', 'asset_yes', 'BUY',
                10.0, 0.57, datetime.now(timezone.utc).isoformat(),
                'Will X happen?', 'will-x-happen', '{}', datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()

        result = SignalService(conn, _settings(str(db_path)), TimeoutMarketService()).run()

        assert result.processed_count == 1
        assert result.rejected_count == 0
        assert result.skipped_count == 1
        row = conn.execute('SELECT decision, reason FROM signals').fetchone()
        assert row is None


def test_signal_service_rejects_excluded_wallet(tmp_path: Path):
    db_path = tmp_path / 'excluded-wallet.db'
    init_db(str(db_path))

    market = MarketInfo(
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

    with get_connection(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO leader_trades (
                wallet, leader_name, transaction_hash, condition_id, asset_id, side,
                size, price, timestamp, market_title, market_slug, raw_json, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                '0xBAD', 'alice', '0xtx', 'cond1', 'asset_yes', 'BUY',
                10.0, 0.57, datetime.now(timezone.utc).isoformat(),
                'Will X happen?', 'will-x-happen', '{}', datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()

        result = SignalService(conn, _settings_with_excluded_wallet(str(db_path), '0xbad'), DummyMarketService(market)).run()

        assert result.processed_count == 1
        assert result.accepted_count == 0
        assert result.rejected_count == 1
        row = conn.execute('SELECT raw_json, decision, reason FROM signals').fetchone()
        assert row['decision'] == 'rejected'
        assert row['reason'] == 'wallet_excluded'
        payload = json.loads(row['raw_json'])
        assert payload['signal_evidence']['stage'] == 'wallet_filter'
        assert payload['signal_evidence']['category'] == 'wallet_filter'
        assert payload['signal_evidence']['reason'] == 'wallet_excluded'


def test_signal_service_rejects_excluded_wallet_with_whitespace_and_missing_condition(tmp_path: Path):
    db_path = tmp_path / 'excluded-wallet-whitespace.db'
    init_db(str(db_path))

    with get_connection(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO leader_trades (
                wallet, leader_name, transaction_hash, condition_id, asset_id, side,
                size, price, timestamp, market_title, market_slug, raw_json, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                '0xBAD', 'alice', '0xtx', None, 'asset_yes', 'BUY',
                10.0, 0.57, datetime.now(timezone.utc).isoformat(),
                'Will X happen?', 'will-x-happen', '{}', datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()

        result = SignalService(conn, _settings_with_excluded_wallet(str(db_path), ' 0xbad '), UnsupportedMarketService()).run()

        assert result.processed_count == 1
        assert result.rejected_count == 1
        row = conn.execute('SELECT raw_json, decision, reason, condition_id FROM signals').fetchone()
        assert row['decision'] == 'rejected'
        assert row['reason'] == 'wallet_excluded'
        assert row['condition_id'] == MISSING_CONDITION_ID
        payload = json.loads(row['raw_json'])
        assert payload['signal_evidence']['stage'] == 'wallet_filter'
        assert payload['signal_evidence']['category'] == 'wallet_filter'



def test_signal_service_rejects_recent_duplicate_signal_with_cooldown(tmp_path: Path):
    db_path = tmp_path / 'cooldown.db'
    init_db(str(db_path))

    market = MarketInfo(
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

    with get_connection(str(db_path)) as conn:
        now = datetime.now(timezone.utc)
        conn.execute(
            """
            INSERT INTO leader_trades (
                wallet, leader_name, transaction_hash, condition_id, asset_id, side,
                size, price, timestamp, market_title, market_slug, raw_json, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                '0x1', 'alice', '0xtx-old', 'cond1', 'asset_yes', 'BUY',
                10.0, 0.57, now.isoformat(), 'Will X happen?', 'will-x-happen', '{}', now.isoformat(),
            ),
        )
        first_trade_id = conn.execute('SELECT id FROM leader_trades ORDER BY id ASC LIMIT 1').fetchone()[0]
        conn.execute(
            """
            INSERT INTO signals (
                leader_trade_id, wallet, leader_name, condition_id, asset_id, market_slug, side,
                leader_price, decision, reason, detected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                first_trade_id, '0x1', 'alice', 'cond1', 'asset_yes', 'will-x-happen', 'BUY',
                0.57, 'accepted', 'accepted', now.isoformat(), '{}',
            ),
        )
        conn.execute(
            """
            INSERT INTO leader_trades (
                wallet, leader_name, transaction_hash, condition_id, asset_id, side,
                size, price, timestamp, market_title, market_slug, raw_json, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                '0x1', 'alice', '0xtx-new', 'cond1', 'asset_yes', 'BUY',
                10.0, 0.58, (now + timedelta(minutes=1)).isoformat(), 'Will X happen?', 'will-x-happen', '{}',
                (now + timedelta(minutes=1)).isoformat(),
            ),
        )
        conn.commit()

        result = SignalService(conn, _settings(str(db_path)), DummyMarketService(market)).run()

        assert result.processed_count == 1
        assert result.accepted_count == 0
        assert result.rejected_count == 1
        row = conn.execute('SELECT raw_json, decision, reason FROM signals ORDER BY id DESC LIMIT 1').fetchone()
        assert row['decision'] == 'rejected'
        assert row['reason'] == 'cooldown_duplicate_signal'
        payload = json.loads(row['raw_json'])
        assert payload['signal_evidence']['stage'] == 'cooldown'
        assert payload['signal_evidence']['category'] == 'cooldown'
        assert payload['signal_evidence']['reason'] == 'cooldown_duplicate_signal'


def test_signal_service_rejects_market_level_duplicate_signal_with_cooldown(tmp_path: Path):
    db_path = tmp_path / 'cooldown-market.db'
    init_db(str(db_path))

    market = MarketInfo(
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

    with get_connection(str(db_path)) as conn:
        now = datetime.now(timezone.utc)
        conn.execute(
            """
            INSERT INTO leader_trades (
                wallet, leader_name, transaction_hash, condition_id, asset_id, side,
                size, price, timestamp, market_title, market_slug, raw_json, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                '0xold', 'alice', '0xtx-old', 'cond1', 'asset_yes', 'BUY',
                10.0, 0.57, now.isoformat(), 'Will X happen?', 'will-x-happen', '{}', now.isoformat(),
            ),
        )
        first_trade_id = conn.execute('SELECT id FROM leader_trades ORDER BY id ASC LIMIT 1').fetchone()[0]
        conn.execute(
            """
            INSERT INTO signals (
                leader_trade_id, wallet, leader_name, condition_id, asset_id, market_slug, side,
                leader_price, decision, reason, detected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                first_trade_id, '0xold', 'alice', 'cond1', 'asset_yes', 'will-x-happen', 'BUY',
                0.57, 'accepted', 'accepted', now.isoformat(), '{}',
            ),
        )
        conn.execute(
            """
            INSERT INTO leader_trades (
                wallet, leader_name, transaction_hash, condition_id, asset_id, side,
                size, price, timestamp, market_title, market_slug, raw_json, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                '0xnew', 'bob', '0xtx-new', 'cond1', 'asset_yes', 'BUY',
                10.0, 0.58, (now + timedelta(minutes=1)).isoformat(), 'Will X happen?', 'will-x-happen', '{}',
                (now + timedelta(minutes=1)).isoformat(),
            ),
        )
        conn.commit()

        result = SignalService(conn, _settings(str(db_path)), DummyMarketService(market)).run()

        assert result.processed_count == 1
        assert result.accepted_count == 0
        assert result.rejected_count == 1
        row = conn.execute('SELECT raw_json, decision, reason FROM signals ORDER BY id DESC LIMIT 1').fetchone()
        assert row['decision'] == 'rejected'
        assert row['reason'] == 'cooldown_duplicate_market_signal'
        payload = json.loads(row['raw_json'])
        assert payload['signal_evidence']['stage'] == 'cooldown'
        assert payload['signal_evidence']['category'] == 'cooldown'
        assert payload['signal_evidence']['reason'] == 'cooldown_duplicate_market_signal'


def test_signal_service_ignores_stale_rejected_signal_for_wallet_cooldown(tmp_path: Path):
    db_path = tmp_path / 'cooldown-ignores-stale-wallet.db'
    init_db(str(db_path))

    market = MarketInfo(
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

    with get_connection(str(db_path)) as conn:
        now = datetime.now(timezone.utc)
        conn.execute(
            """
            INSERT INTO leader_trades (
                wallet, leader_name, transaction_hash, condition_id, asset_id, side,
                size, price, timestamp, market_title, market_slug, raw_json, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                '0x1', 'alice', '0xtx-old', 'cond1', 'asset_yes', 'BUY',
                10.0, 0.57, (now - timedelta(minutes=20)).isoformat(), 'Will X happen?', 'will-x-happen', '{}', now.isoformat(),
            ),
        )
        first_trade_id = conn.execute('SELECT id FROM leader_trades ORDER BY id ASC LIMIT 1').fetchone()[0]
        conn.execute(
            """
            INSERT INTO signals (
                leader_trade_id, wallet, leader_name, condition_id, asset_id, market_slug, side,
                leader_price, decision, reason, detected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                first_trade_id, '0x1', 'alice', 'cond1', 'asset_yes', 'will-x-happen', 'BUY',
                0.57, 'accepted', 'accepted', now.isoformat(), '{}',
            ),
        )
        first_signal_id = conn.execute('SELECT id FROM signals ORDER BY id ASC LIMIT 1').fetchone()[0]
        conn.execute(
            """
            INSERT INTO sim_orders (
                signal_id, condition_id, asset_id, market_slug, side,
                requested_notional, filled_notional, filled_shares, fill_price,
                leader_price, slippage_pct, status, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                first_signal_id, 'cond1', 'asset_yes', 'will-x-happen', 'BUY',
                '100.00', '0.00', '0.000000', None, '0.570000', None, 'rejected', 'signal_stale', now.isoformat(),
            ),
        )
        conn.execute(
            """
            INSERT INTO leader_trades (
                wallet, leader_name, transaction_hash, condition_id, asset_id, side,
                size, price, timestamp, market_title, market_slug, raw_json, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                '0x1', 'alice', '0xtx-new', 'cond1', 'asset_yes', 'BUY',
                10.0, 0.58, now.isoformat(), 'Will X happen?', 'will-x-happen', '{}', now.isoformat(),
            ),
        )
        conn.commit()

        result = SignalService(conn, _settings(str(db_path)), DummyMarketService(market)).run()

        assert result.processed_count == 1
        assert result.accepted_count == 1
        row = conn.execute('SELECT decision, reason FROM signals ORDER BY id DESC LIMIT 1').fetchone()
        assert dict(row) == {'decision': 'accepted', 'reason': 'accepted'}


def test_signal_service_ignores_stale_rejected_signal_for_market_cooldown(tmp_path: Path):
    db_path = tmp_path / 'cooldown-ignores-stale-market.db'
    init_db(str(db_path))

    market = MarketInfo(
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

    with get_connection(str(db_path)) as conn:
        now = datetime.now(timezone.utc)
        conn.execute(
            """
            INSERT INTO leader_trades (
                wallet, leader_name, transaction_hash, condition_id, asset_id, side,
                size, price, timestamp, market_title, market_slug, raw_json, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                '0xold', 'alice', '0xtx-old', 'cond1', 'asset_yes', 'BUY',
                10.0, 0.57, (now - timedelta(minutes=20)).isoformat(), 'Will X happen?', 'will-x-happen', '{}', now.isoformat(),
            ),
        )
        first_trade_id = conn.execute('SELECT id FROM leader_trades ORDER BY id ASC LIMIT 1').fetchone()[0]
        conn.execute(
            """
            INSERT INTO signals (
                leader_trade_id, wallet, leader_name, condition_id, asset_id, market_slug, side,
                leader_price, decision, reason, detected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                first_trade_id, '0xold', 'alice', 'cond1', 'asset_yes', 'will-x-happen', 'BUY',
                0.57, 'accepted', 'accepted', now.isoformat(), '{}',
            ),
        )
        first_signal_id = conn.execute('SELECT id FROM signals ORDER BY id ASC LIMIT 1').fetchone()[0]
        conn.execute(
            """
            INSERT INTO sim_orders (
                signal_id, condition_id, asset_id, market_slug, side,
                requested_notional, filled_notional, filled_shares, fill_price,
                leader_price, slippage_pct, status, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                first_signal_id, 'cond1', 'asset_yes', 'will-x-happen', 'BUY',
                '100.00', '0.00', '0.000000', None, '0.570000', None, 'rejected', 'trade_too_old_at_fill', now.isoformat(),
            ),
        )
        conn.execute(
            """
            INSERT INTO leader_trades (
                wallet, leader_name, transaction_hash, condition_id, asset_id, side,
                size, price, timestamp, market_title, market_slug, raw_json, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                '0xnew', 'bob', '0xtx-new', 'cond1', 'asset_yes', 'BUY',
                10.0, 0.58, now.isoformat(), 'Will X happen?', 'will-x-happen', '{}', now.isoformat(),
            ),
        )
        conn.commit()

        result = SignalService(conn, _settings(str(db_path)), DummyMarketService(market)).run()

        assert result.processed_count == 1
        assert result.accepted_count == 1
        row = conn.execute('SELECT decision, reason FROM signals ORDER BY id DESC LIMIT 1').fetchone()
        assert dict(row) == {'decision': 'accepted', 'reason': 'accepted'}
