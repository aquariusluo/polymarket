from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from app.config import Settings
from app.domain.models import MarketInfo
from app.jobs import run_backfill_signals
from app.storage.db import get_connection, init_db


class DummyBookClient:
    def __init__(self, asks=None, bids=None):
        self.asks = asks or [{'price': 0.58, 'size': 500.0}]
        self.bids = bids or [{'price': 0.57, 'size': 500.0}]

    def fetch_book(self, token_id: str):
        return {
            'asks': self.asks,
            'bids': self.bids,
        }


class DummyMarketService:
    def __init__(self, conn, settings):
        self.market_client = DummyBookClient(asks=[{'price': 0.90, 'size': 500.0}])


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


def test_run_backfill_signals_reclassifies_legacy_non_copyable_accepts(tmp_path: Path):
    db_path = tmp_path / 'backfill.db'
    init_db(str(db_path))
    now = datetime.now(timezone.utc).isoformat()

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
                10.0, 0.57, now, 'Will X happen?', 'will-x-happen', '{}', now,
            ),
        )
        trade_id = conn.execute('SELECT id FROM leader_trades').fetchone()[0]
        conn.execute(
            """
            INSERT INTO signals (
                leader_trade_id, wallet, leader_name, condition_id, asset_id,
                market_slug, side, leader_price, decision, reason, detected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (trade_id, '0x1', 'alice', 'cond1', 'asset_yes', 'will-x-happen', 'BUY', 0.57, 'accepted', 'accepted', now, '{}'),
        )
        signal_id = conn.execute('SELECT id FROM signals').fetchone()[0]
        conn.execute(
            """
            INSERT INTO sim_orders (
                signal_id, condition_id, asset_id, market_slug, side, requested_notional,
                filled_notional, filled_shares, fill_price, leader_price, slippage_pct,
                status, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (signal_id, 'cond1', 'asset_yes', 'will-x-happen', 'BUY', 100.0, 0.0, 0.0, 0.90, 0.57, 57.89, 'rejected', 'slippage_too_high', now),
        )
        conn.commit()

        result = run_backfill_signals.run(_settings(str(db_path)), conn=conn, market_service_cls=DummyMarketService)

        assert result['checked'] == 1
        assert result['reclassified'] == 1
        assert result['sim_orders_deleted'] == 1

        signal = conn.execute('SELECT decision, reason FROM signals WHERE id = ?', (signal_id,)).fetchone()
        remaining_orders = conn.execute('SELECT COUNT(*) FROM sim_orders WHERE signal_id = ?', (signal_id,)).fetchone()[0]
        assert dict(signal) == {'decision': 'rejected', 'reason': 'book_spread_too_wide'}
        assert remaining_orders == 0


def test_run_backfill_signals_skips_filled_or_still_copyable_signals(tmp_path: Path):
    db_path = tmp_path / 'backfill-skip.db'
    init_db(str(db_path))
    now = datetime.now(timezone.utc)
    old = (now - timedelta(minutes=1)).isoformat()

    with get_connection(str(db_path)) as conn:
        for tx_hash, asset_id in [('0xtx1', 'asset_yes_1'), ('0xtx2', 'asset_yes_2')]:
            conn.execute(
                """
                INSERT INTO leader_trades (
                    wallet, leader_name, transaction_hash, condition_id, asset_id, side,
                    size, price, timestamp, market_title, market_slug, raw_json, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ('0x1', 'alice', tx_hash, tx_hash, asset_id, 'BUY', 10.0, 0.57, old, 'Will X happen?', 'will-x-happen', '{}', old),
            )
        trade_ids = [row[0] for row in conn.execute('SELECT id FROM leader_trades ORDER BY id').fetchall()]
        conn.execute(
            """
            INSERT INTO signals (
                leader_trade_id, wallet, leader_name, condition_id, asset_id,
                market_slug, side, leader_price, decision, reason, detected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (trade_ids[0], '0x1', 'alice', 'cond-filled', 'asset_yes_1', 'will-x-happen', 'BUY', 0.57, 'accepted', 'accepted', old, '{}'),
        )
        conn.execute(
            """
            INSERT INTO signals (
                leader_trade_id, wallet, leader_name, condition_id, asset_id,
                market_slug, side, leader_price, decision, reason, detected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (trade_ids[1], '0x1', 'alice', 'cond-ok', 'asset_yes_2', 'will-x-happen', 'BUY', 0.57, 'accepted', 'accepted', old, '{}'),
        )
        signal_ids = [row[0] for row in conn.execute('SELECT id FROM signals ORDER BY id').fetchall()]
        conn.execute(
            """
            INSERT INTO sim_orders (
                signal_id, condition_id, asset_id, market_slug, side, requested_notional,
                filled_notional, filled_shares, fill_price, leader_price, slippage_pct,
                status, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (signal_ids[0], 'cond-filled', 'asset_yes_1', 'will-x-happen', 'BUY', 100.0, 100.0, 175.0, 0.57, 0.57, 0.0, 'filled', 'filled', old),
        )
        conn.commit()

        class CopyableMarketService:
            def __init__(self, conn, settings):
                self.market_client = DummyBookClient(asks=[{'price': 0.58, 'size': 500.0}])

        result = run_backfill_signals.run(_settings(str(db_path)), conn=conn, market_service_cls=CopyableMarketService)

        assert result['checked'] == 1
        assert result['reclassified'] == 0
        decisions = [tuple(row) for row in conn.execute('SELECT decision, reason FROM signals ORDER BY id').fetchall()]
        assert decisions == [('accepted', 'accepted'), ('accepted', 'accepted')]


def test_run_backfill_signals_uses_historical_slippage_reject_when_book_is_unavailable(tmp_path: Path):
    db_path = tmp_path / 'backfill-book-unavailable.db'
    init_db(str(db_path))
    now = datetime.now(timezone.utc).isoformat()

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
                10.0, 0.57, now, 'Will X happen?', 'will-x-happen', '{}', now,
            ),
        )
        trade_id = conn.execute('SELECT id FROM leader_trades').fetchone()[0]
        conn.execute(
            """
            INSERT INTO signals (
                leader_trade_id, wallet, leader_name, condition_id, asset_id,
                market_slug, side, leader_price, decision, reason, detected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (trade_id, '0x1', 'alice', 'cond1', 'asset_yes', 'will-x-happen', 'BUY', 0.57, 'accepted', 'accepted', now, '{}'),
        )
        signal_id = conn.execute('SELECT id FROM signals').fetchone()[0]
        conn.execute(
            """
            INSERT INTO sim_orders (
                signal_id, condition_id, asset_id, market_slug, side, requested_notional,
                filled_notional, filled_shares, fill_price, leader_price, slippage_pct,
                status, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (signal_id, 'cond1', 'asset_yes', 'will-x-happen', 'BUY', 100.0, 0.0, 0.0, 0.90, 0.57, 57.89, 'rejected', 'slippage_too_high', now),
        )
        conn.commit()

        class UnavailableMarketService:
            def __init__(self, conn, settings):
                class RaisingBookClient:
                    def fetch_book(self, token_id: str):
                        raise httpx.ReadTimeout('book unavailable')
                self.market_client = RaisingBookClient()

        result = run_backfill_signals.run(_settings(str(db_path)), conn=conn, market_service_cls=UnavailableMarketService)

        assert result['checked'] == 2
        assert result['reclassified'] == 1
        signal = conn.execute('SELECT decision, reason FROM signals WHERE id = ?', (signal_id,)).fetchone()
        assert dict(signal) == {'decision': 'rejected', 'reason': 'book_slippage_too_high'}


def test_run_backfill_signals_normalizes_signal_reason_to_book_spread_too_wide(tmp_path: Path):
    db_path = tmp_path / 'backfill-normalize-reason.db'
    init_db(str(db_path))
    now = datetime.now(timezone.utc).isoformat()

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
                10.0, 0.98, now, 'Will X happen?', 'will-x-happen', '{}', now,
            ),
        )
        trade_id = conn.execute('SELECT id FROM leader_trades').fetchone()[0]
        conn.execute(
            """
            INSERT INTO signals (
                leader_trade_id, wallet, leader_name, condition_id, asset_id,
                market_slug, side, leader_price, decision, reason, detected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (trade_id, '0x1', 'alice', 'cond1', 'asset_yes', 'will-x-happen', 'BUY', 0.98, 'rejected', 'book_slippage_too_high', now, '{}'),
        )
        conn.commit()

        class WideBookMarketService:
            def __init__(self, conn, settings):
                self.market_client = DummyBookClient(
                    asks=[{'price': 0.99, 'size': 500.0}],
                    bids=[{'price': 0.01, 'size': 500.0}],
                )

        result = run_backfill_signals.run(_settings(str(db_path)), conn=conn, market_service_cls=WideBookMarketService)

        assert result['checked'] == 1
        assert result['reason_normalized'] == 1
        signal = conn.execute('SELECT decision, reason FROM signals').fetchone()
        assert dict(signal) == {'decision': 'rejected', 'reason': 'book_spread_too_wide'}


def test_run_backfill_signals_uses_saved_copyability_snapshot_before_live_book(tmp_path: Path):
    db_path = tmp_path / 'backfill-snapshot.db'
    init_db(str(db_path))
    now = datetime.now(timezone.utc).isoformat()

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
                10.0, 0.98, now, 'Will X happen?', 'will-x-happen', '{}', now,
            ),
        )
        trade_id = conn.execute('SELECT id FROM leader_trades').fetchone()[0]
        conn.execute(
            """
            INSERT INTO signals (
                leader_trade_id, wallet, leader_name, condition_id, asset_id,
                market_slug, side, leader_price, decision, reason, detected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade_id,
                '0x1',
                'alice',
                'cond1',
                'asset_yes',
                'will-x-happen',
                'BUY',
                0.98,
                'accepted',
                'accepted',
                now,
                '{"copyability":{"source":"live_book","best_ask_price":0.99,"best_ask_size":500.0,"best_bid_price":0.01,"spread":0.98,"leader_price":0.98,"slippage_pct":1.02,"reason":"book_spread_too_wide"}}',
            ),
        )
        conn.commit()

        class UnavailableMarketService:
            def __init__(self, conn, settings):
                class RaisingBookClient:
                    def fetch_book(self, token_id: str):
                        raise httpx.ReadTimeout('book unavailable')
                self.market_client = RaisingBookClient()

        result = run_backfill_signals.run(_settings(str(db_path)), conn=conn, market_service_cls=UnavailableMarketService)

        assert result['checked'] == 1
        assert result['reclassified'] == 1
        signal = conn.execute('SELECT decision, reason FROM signals').fetchone()
        assert dict(signal) == {'decision': 'rejected', 'reason': 'book_spread_too_wide'}
