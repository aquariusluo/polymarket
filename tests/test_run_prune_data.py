from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import Settings
from app.jobs import run_prune_data
from app.storage.db import get_connection, init_db


def _settings(db_path: str) -> Settings:
    return Settings(
        app_env='test',
        db_path=db_path,
        leaderboard_category='overall',
        leaderboard_time='30d',
        leaderboard_sort='profit',
        top_n=5,
        poll_interval_seconds=1,
        trade_fetch_limit=5,
        min_time_to_expiry_hours=24,
        min_market_liquidity=1000.0,
        signal_cooldown_minutes=5,
        data_source='http',
        retention_days_leader_trades=30,
        retention_days_signals=30,
        retention_days_job_runs=30,
        retention_days_portfolio_snapshots=30,
    )


def test_run_prune_data_prunes_old_unreferenced_rows(tmp_path: Path):
    db_path = tmp_path / 'prune.db'
    init_db(str(db_path))
    old_iso = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()

    with get_connection(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO leader_trades (
                wallet, leader_name, transaction_hash, condition_id, asset_id, side,
                size, price, timestamp, market_title, market_slug, raw_json, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ('0xold', 'old', '0xold-nosig', 'cond1', 'asset1', 'BUY', '1.000000', '0.500000', old_iso, 'M1', 'm1', '{}', old_iso),
        )
        conn.execute(
            """
            INSERT INTO leader_trades (
                wallet, leader_name, transaction_hash, condition_id, asset_id, side,
                size, price, timestamp, market_title, market_slug, raw_json, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ('0xkeep', 'keep', '0xold-sig', 'cond2', 'asset2', 'BUY', '1.000000', '0.500000', old_iso, 'M2', 'm2', '{}', old_iso),
        )
        conn.execute(
            """
            INSERT INTO leader_trades (
                wallet, leader_name, transaction_hash, condition_id, asset_id, side,
                size, price, timestamp, market_title, market_slug, raw_json, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ('0xdrop', 'drop', '0xold-sig-drop', 'cond3', 'asset3', 'BUY', '1.000000', '0.500000', old_iso, 'M3', 'm3', '{}', old_iso),
        )
        keep_trade_id = conn.execute(
            "SELECT id FROM leader_trades WHERE transaction_hash='0xold-sig'"
        ).fetchone()[0]
        drop_trade_id = conn.execute(
            "SELECT id FROM leader_trades WHERE transaction_hash='0xold-sig-drop'"
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO signals (
                leader_trade_id, wallet, leader_name, condition_id, asset_id, market_slug, side,
                leader_price, decision, reason, detected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (keep_trade_id, '0xkeep', 'keep', 'cond2', 'asset2', 'm2', 'BUY', '0.500000', 'accepted', 'accepted', old_iso, '{}'),
        )
        keep_signal_id = conn.execute("SELECT id FROM signals WHERE wallet='0xkeep'").fetchone()[0]
        conn.execute(
            """
            INSERT INTO signals (
                leader_trade_id, wallet, leader_name, condition_id, asset_id, market_slug, side,
                leader_price, decision, reason, detected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (drop_trade_id, '0xdrop', 'drop', 'cond3', 'asset3', 'm3', 'BUY', '0.500000', 'accepted', 'accepted', old_iso, '{}'),
        )
        conn.execute(
            """
            INSERT INTO sim_orders (
                signal_id, condition_id, asset_id, market_slug, side,
                requested_notional, filled_notional, filled_shares, fill_price, leader_price, slippage_pct,
                status, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (keep_signal_id, 'cond2', 'asset2', 'm2', 'BUY', '10.00', '10.00', '20.000000', '0.500000', '0.500000', '0.0000', 'filled', 'filled', now_iso),
        )
        old_job_id = conn.execute(
            """
            INSERT INTO job_runs (job_name, started_at, finished_at, status, inserted_count, skipped_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ('old-job', old_iso, old_iso, 'completed', 0, 0),
        ).lastrowid
        conn.execute(
            """
            INSERT INTO job_runs (job_name, started_at, finished_at, status, inserted_count, skipped_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ('new-job', now_iso, now_iso, 'completed', 0, 0),
        )
        conn.execute(
            """
            INSERT INTO portfolio_snapshots (
                captured_at, total_cost_basis, total_market_value,
                total_unrealized_pnl, total_realized_pnl, total_equity, drawdown_pct, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (old_iso, '100.00', '120.00', '20.00', '0.00', '120.00', '0.0000', '{}'),
        )
        conn.execute(
            """
            INSERT INTO portfolio_snapshots (
                captured_at, total_cost_basis, total_market_value,
                total_unrealized_pnl, total_realized_pnl, total_equity, drawdown_pct, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (now_iso, '130.00', '125.00', '-5.00', '0.00', '125.00', '4.0000', '{}'),
        )
        conn.commit()

        result = run_prune_data.run(_settings(str(db_path)), conn=conn)

        assert result['pruned_leader_trades'] == 2
        assert result['pruned_signals'] == 1
        assert result['pruned_job_runs'] == 1
        assert result['pruned_portfolio_snapshots'] == 1
        assert result['total_pruned'] == 5

        trade_hashes = [r['transaction_hash'] for r in conn.execute("SELECT transaction_hash FROM leader_trades ORDER BY id ASC").fetchall()]
        signal_wallets = [r['wallet'] for r in conn.execute("SELECT wallet FROM signals ORDER BY id ASC").fetchall()]
        job_names = [r['job_name'] for r in conn.execute("SELECT job_name FROM job_runs ORDER BY id ASC").fetchall()]
        snapshots = [r['captured_at'] for r in conn.execute("SELECT captured_at FROM portfolio_snapshots ORDER BY id ASC").fetchall()]

        assert trade_hashes == ['0xold-sig']
        assert signal_wallets == ['0xkeep']
        assert job_names == ['new-job', 'prune-data']
        assert snapshots == [now_iso]
        assert old_job_id not in [r['id'] for r in conn.execute("SELECT id FROM job_runs").fetchall()]
