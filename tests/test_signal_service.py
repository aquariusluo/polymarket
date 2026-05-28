from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.domain.models import MarketInfo
from app.services.signal_service import SignalService
from app.storage.db import get_connection, init_db


class DummyMarketService:
    def __init__(self, market_info: MarketInfo):
        self.market_info = market_info

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
        row = conn.execute('SELECT decision, reason FROM signals').fetchone()
        assert row['decision'] == 'rejected'
        assert row['reason'] == 'market_unsupported'


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
        row = conn.execute('SELECT decision, reason FROM signals ORDER BY id DESC LIMIT 1').fetchone()
        assert row['decision'] == 'rejected'
        assert row['reason'] == 'cooldown_duplicate_signal'


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
        row = conn.execute('SELECT decision, reason FROM signals ORDER BY id DESC LIMIT 1').fetchone()
        assert row['decision'] == 'rejected'
        assert row['reason'] == 'cooldown_duplicate_market_signal'
