from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.models import Decision, Leader, LeaderTrade, MarketInfo, Side, SignalDecision
from app.storage.repositories import (
    JobRunRepository,
    LeaderRepository,
    LeaderTradeRepository,
    MarketRepository,
    PortfolioSnapshotRepository,
    PositionRepository,
    SignalRepository,
    SimOrderRepository,
)


def test_leader_repository_tracks_latest_selection(db_conn, sample_leader):
    repo = LeaderRepository(db_conn)
    older = sample_leader
    newer = Leader(
        rank=1,
        wallet='0xnew',
        name='Bob',
        pseudonym='bob',
        pnl_snapshot=99.0,
        volume_snapshot=88.0,
        raw_json={'wallet': '0xnew'},
    )

    assert repo.has_any_leaders() is False
    assert repo.insert_many([older], selection_run_id='run-1') == 1
    assert repo.insert_many([newer], selection_run_id='run-2') == 1

    latest = repo.get_latest_leaders()
    assert repo.has_any_leaders() is True
    assert repo.get_latest_selection_run_id() == 'run-2'
    assert [row['wallet'] for row in latest] == ['0xnew']


def test_leader_trade_repository_lists_rows_without_signals(db_conn, sample_trade, insert_signal_for_trade):
    trade_repo = LeaderTradeRepository(db_conn)
    assert trade_repo.insert_if_new(sample_trade) is True
    rows = trade_repo.list_without_signal()
    assert trade_repo.count_all() == 1
    assert len(rows) == 1
    assert rows[0]['transaction_hash'] == sample_trade.transaction_hash

    db_conn.execute('DELETE FROM leader_trades')
    db_conn.commit()
    inserted, _ = insert_signal_for_trade()
    assert inserted is True
    assert trade_repo.list_without_signal() == []


def test_market_repository_upsert_round_trips_and_updates_market(db_conn, sample_market):
    repo = MarketRepository(db_conn)
    repo.upsert(sample_market)
    loaded = repo.get_by_condition_id(sample_market.condition_id)
    assert loaded is not None
    assert loaded.slug == sample_market.slug
    assert loaded.refreshed_at == sample_market.refreshed_at
    assert loaded.raw_json['condition_id'] == sample_market.condition_id

    updated = MarketInfo(
        condition_id=sample_market.condition_id,
        title='Updated market',
        slug='updated-slug',
        end_time=sample_market.end_time,
        liquidity=12345.0,
        active=False,
        closed=True,
        yes_token_id='yes-2',
        no_token_id='no-2',
        yes_outcome='Yes',
        no_outcome='No',
        raw_json={'condition_id': sample_market.condition_id, 'rev': 2},
        refreshed_at=sample_market.refreshed_at + timedelta(minutes=5),
    )
    repo.upsert(updated)
    reloaded = repo.get_by_condition_id(sample_market.condition_id)
    assert reloaded is not None
    assert reloaded.title == 'Updated market'
    assert reloaded.slug == 'updated-slug'
    assert reloaded.active is False
    assert reloaded.closed is True
    assert reloaded.raw_json['rev'] == 2
    assert repo.get_by_condition_id('missing-cond') is None


def test_signal_repository_supports_cooldown_counts_and_pending_rows(db_conn, insert_signal_for_trade):
    inserted, signal_row = insert_signal_for_trade()
    signal_repo = SignalRepository(db_conn)

    assert inserted is True
    assert signal_repo.has_recent_accepted_signal('0xleader', 'cond-1', 'asset-1', cooldown_minutes=5) is True
    assert signal_repo.counts() == {'accepted': 1}
    pending = signal_repo.list_pending_accepted()
    assert len(pending) == 1
    assert pending[0]['id'] == signal_row['id']


def test_signal_repository_handles_expired_cooldown_and_multiple_decisions(db_conn, insert_signal_for_trade):
    old_iso = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    inserted, _ = insert_signal_for_trade(detected_at=old_iso)
    assert inserted is True

    db_conn.execute(
        """
        INSERT INTO leader_trades (
            wallet, leader_name, transaction_hash, condition_id, asset_id, side,
            size, price, timestamp, market_title, market_slug, raw_json, ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            '0xleader', 'alice', '0xsecond-tx', 'cond-2', 'asset-2', 'BUY', 1.0, 0.5,
            datetime.now(timezone.utc).isoformat(), 'Market 2', 'market-2', '{}', datetime.now(timezone.utc).isoformat(),
        ),
    )
    second_trade_id = db_conn.execute('SELECT id FROM leader_trades WHERE transaction_hash = ?', ('0xsecond-tx',)).fetchone()[0]
    db_conn.execute(
        """
        INSERT INTO signals (
            leader_trade_id, wallet, leader_name, condition_id, asset_id, market_slug, side,
            leader_price, decision, reason, detected_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (second_trade_id, '0xleader', 'alice', 'cond-2', 'asset-2', 'market-2', 'BUY', 0.5, 'rejected', 'liquidity_too_low', datetime.now(timezone.utc).isoformat(), '{}'),
    )
    db_conn.commit()

    signal_repo = SignalRepository(db_conn)
    assert signal_repo.has_recent_accepted_signal('0xleader', 'cond-1', 'asset-1', cooldown_minutes=5) is False
    assert signal_repo.counts() == {'accepted': 1, 'rejected': 1}


def test_signal_repository_pending_rows_include_exact_trade_timestamp(db_conn, insert_signal_for_trade):
    inserted, signal_row = insert_signal_for_trade()
    assert inserted is True

    trade_row = db_conn.execute(
        'SELECT timestamp FROM leader_trades WHERE id = ?',
        (signal_row['leader_trade_id'],),
    ).fetchone()
    pending = SignalRepository(db_conn).list_pending_accepted()

    assert len(pending) == 1
    assert pending[0]['trade_timestamp'] == trade_row['timestamp']


def test_sim_order_repository_count_helpers_and_pending_signal_interaction(db_conn, insert_signal_for_trade):
    _, signal_row = insert_signal_for_trade()
    repo = SimOrderRepository(db_conn)
    row_id = repo.insert(
        signal_id=int(signal_row['id']),
        condition_id='cond-1',
        asset_id='asset-1',
        market_slug='will-x-happen',
        side='BUY',
        requested_notional=100.0,
        filled_notional=100.0,
        filled_shares=161.29,
        fill_price=0.62,
        leader_price=0.61,
        slippage_pct=1.64,
        status='filled',
        reason='filled',
    )
    since_iso = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()

    assert row_id > 0
    assert repo.count_by_status('filled') == 1
    assert repo.count_by_status('rejected') == 0
    assert repo.count_filled_since(since_iso) == 1
    assert SignalRepository(db_conn).list_pending_accepted() == []


def test_position_repository_rolls_up_cost_basis_and_missing_position_defaults(db_conn):
    repo = PositionRepository(db_conn)
    assert repo.get('missing', 'asset') is None
    assert repo.current_cost_basis('missing', 'asset') == 0.0
    assert repo.current_market_cost_basis('missing') == 0.0
    assert repo.total_cost_basis() == 0.0

    repo.upsert_buy('cond-1', 'asset-1', 'slug-1', 'BUY', shares=10.0, fill_price=0.4)
    repo.upsert_buy('cond-1', 'asset-1', 'slug-1', 'BUY', shares=5.0, fill_price=0.6)
    repo.upsert_buy('cond-2', 'asset-2', 'slug-2', 'BUY', shares=2.0, fill_price=1.5)

    pos = repo.get('cond-1', 'asset-1')
    assert pos is not None
    assert round(pos.shares, 2) == 15.0
    assert round(pos.avg_cost, 4) == round((10.0 * 0.4 + 5.0 * 0.6) / 15.0, 4)
    assert repo.current_cost_basis('cond-1', 'asset-1') == pos.cost_basis
    assert repo.current_market_cost_basis('cond-1') == pos.cost_basis
    assert repo.total_cost_basis() == pos.cost_basis + 3.0
    assert len(repo.list_all()) == 2
    repo.delete('cond-2', 'asset-2')
    assert repo.get('cond-2', 'asset-2') is None


def test_portfolio_snapshot_repository_supports_summary_queries_and_empty_boundaries(db_conn, insert_snapshot):
    repo = PortfolioSnapshotRepository(db_conn)
    assert repo.count() == 0
    assert repo.first() is None
    assert repo.latest() is None
    assert repo.max_drawdown_pct() == 0.0
    assert repo.compute_drawdown_pct(0.0) == 0.0

    first_id = insert_snapshot(
        total_cost_basis=100.0,
        total_market_value=110.0,
        total_unrealized_pnl=10.0,
        total_realized_pnl=0.0,
        total_equity=110.0,
        drawdown_pct=0.0,
    )
    second_id = insert_snapshot(
        total_cost_basis=100.0,
        total_market_value=80.0,
        total_unrealized_pnl=-20.0,
        total_realized_pnl=0.0,
        total_equity=80.0,
        drawdown_pct=27.27,
    )

    assert repo.count() == 2
    assert repo.first() is not None and repo.first().id == first_id
    assert repo.latest() is not None and repo.latest().id == second_id
    assert round(repo.max_drawdown_pct(), 2) == 27.27
    assert round(repo.compute_drawdown_pct(70.0), 2) == round(((110.0 - 70.0) / 110.0) * 100.0, 2)


def test_portfolio_snapshot_repository_prune_older_than(db_conn):
    repo = PortfolioSnapshotRepository(db_conn)
    old_iso = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()
    db_conn.execute(
        """
        INSERT INTO portfolio_snapshots (
            captured_at, total_cost_basis, total_market_value,
            total_unrealized_pnl, total_realized_pnl, total_equity, drawdown_pct, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (old_iso, '100.00', '110.00', '10.00', '0.00', '110.00', '0.0000', '{}'),
    )
    db_conn.execute(
        """
        INSERT INTO portfolio_snapshots (
            captured_at, total_cost_basis, total_market_value,
            total_unrealized_pnl, total_realized_pnl, total_equity, drawdown_pct, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (now_iso, '100.00', '90.00', '-10.00', '0.00', '90.00', '18.0000', '{}'),
    )
    db_conn.commit()

    pruned = repo.prune_older_than((datetime.now(timezone.utc) - timedelta(days=30)).isoformat())
    assert pruned == 1
    assert repo.count() == 1


def test_job_run_repository_records_start_finish_and_failure_message(db_conn):
    repo = JobRunRepository(db_conn)
    run_id = repo.start('demo-job')
    repo.finish(run_id, status='completed', inserted_count=3, skipped_count=1)

    row = db_conn.execute('SELECT * FROM job_runs WHERE id = ?', (run_id,)).fetchone()
    assert row['job_name'] == 'demo-job'
    assert row['status'] == 'completed'
    assert row['inserted_count'] == 3
    assert row['skipped_count'] == 1
    assert row['finished_at'] is not None

    failed_id = repo.start('bad-job')
    repo.finish(failed_id, status='failed', error_message='boom')
    failed_row = db_conn.execute('SELECT * FROM job_runs WHERE id = ?', (failed_id,)).fetchone()
    assert failed_row['status'] == 'failed'
    assert failed_row['error_message'] == 'boom'



def test_leader_trade_repository_respects_limit_and_timestamp_order(db_conn, sample_trade):
    repo = LeaderTradeRepository(db_conn)
    older = sample_trade
    newer = LeaderTrade(
        wallet='0xleader',
        leader_name='alice',
        transaction_hash='0xnewer',
        condition_id='cond-1',
        asset_id='asset-2',
        side='BUY',
        size=1.0,
        price=0.7,
        timestamp=datetime.now(timezone.utc),
        market_title='Later market',
        market_slug='later-market',
        raw_json={'tx': '0xnewer'},
    )

    assert repo.insert_if_new(newer) is True
    assert repo.insert_if_new(older) is True

    rows = repo.list_without_signal(limit=1)
    assert len(rows) == 1
    assert rows[0]['transaction_hash'] == newer.transaction_hash


def test_signal_repository_pending_limit_returns_oldest_accepted_first(db_conn, insert_signal_for_trade, sample_trade):
    inserted, first_signal = insert_signal_for_trade()
    assert inserted is True

    second_trade = LeaderTrade(
        wallet='0xleader',
        leader_name='alice',
        transaction_hash='0xpending-2',
        condition_id='cond-2',
        asset_id='asset-2',
        side='BUY',
        size=2.0,
        price=0.55,
        timestamp=datetime.now(timezone.utc),
        market_title='Second market',
        market_slug='second-market',
        raw_json={'tx': '0xpending-2'},
    )
    trade_repo = LeaderTradeRepository(db_conn)
    assert trade_repo.insert_if_new(second_trade) is True
    second_trade_row = db_conn.execute(
        'SELECT * FROM leader_trades WHERE transaction_hash = ?',
        ('0xpending-2',),
    ).fetchone()
    second_decision = SignalDecision(
        leader_trade_id=int(second_trade_row['id']),
        condition_id='cond-2',
        asset_id='asset-2',
        decision=Decision.ACCEPTED,
        reason='accepted',
        side=Side.BUY,
        price=0.55,
        market_slug='second-market',
    )
    assert SignalRepository(db_conn).insert_if_new(second_trade, second_decision) is True

    pending = SignalRepository(db_conn).list_pending_accepted(limit=1)
    assert len(pending) == 1
    assert pending[0]['id'] == first_signal['id']


def test_portfolio_snapshot_repository_insert_round_trips_raw_json(db_conn):
    repo = PortfolioSnapshotRepository(db_conn)
    snapshot_id = repo.insert(
        total_cost_basis=50.0,
        total_market_value=52.5,
        total_unrealized_pnl=2.5,
        total_realized_pnl=1.0,
        total_equity=53.5,
        drawdown_pct=0.0,
        raw_json={'positions': [{'asset_id': 'asset-1', 'shares': 3}]},
    )

    loaded = repo.latest()
    assert loaded is not None
    assert loaded.id == snapshot_id
    assert loaded.raw_json['positions'][0]['asset_id'] == 'asset-1'


def test_job_run_repository_start_defaults_running_status_and_zero_counts(db_conn):
    repo = JobRunRepository(db_conn)
    run_id = repo.start('seed-job')
    row = db_conn.execute('SELECT * FROM job_runs WHERE id = ?', (run_id,)).fetchone()
    assert row['status'] == 'running'
    assert row['inserted_count'] == 0
    assert row['skipped_count'] == 0
    assert row['finished_at'] is None


def test_leader_trade_repository_prune_keeps_rows_with_signals(db_conn):
    trade_repo = LeaderTradeRepository(db_conn)
    now_iso = datetime.now(timezone.utc).isoformat()
    old_iso = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()

    db_conn.execute(
        """
        INSERT INTO leader_trades (
            wallet, leader_name, transaction_hash, condition_id, asset_id, side,
            size, price, timestamp, market_title, market_slug, raw_json, ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ('0x1', 'old-no-signal', '0xold-nosig', 'cond-old', 'asset-old', 'BUY', 1.0, 0.5, old_iso, 'Old', 'old', '{}', old_iso),
    )
    db_conn.execute(
        """
        INSERT INTO leader_trades (
            wallet, leader_name, transaction_hash, condition_id, asset_id, side,
            size, price, timestamp, market_title, market_slug, raw_json, ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ('0x2', 'old-with-signal', '0xold-sig', 'cond-old2', 'asset-old2', 'BUY', 1.0, 0.5, old_iso, 'Old 2', 'old-2', '{}', old_iso),
    )
    trade_id_with_signal = db_conn.execute(
        "SELECT id FROM leader_trades WHERE transaction_hash = ?",
        ('0xold-sig',),
    ).fetchone()[0]
    db_conn.execute(
        """
        INSERT INTO signals (
            leader_trade_id, wallet, leader_name, condition_id, asset_id, market_slug, side,
            leader_price, decision, reason, detected_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (trade_id_with_signal, '0x2', 'old-with-signal', 'cond-old2', 'asset-old2', 'old-2', 'BUY', 0.5, 'accepted', 'accepted', now_iso, '{}'),
    )
    db_conn.commit()

    pruned = trade_repo.prune_older_than((datetime.now(timezone.utc) - timedelta(days=30)).isoformat())
    assert pruned == 1
    remaining = db_conn.execute("SELECT transaction_hash FROM leader_trades ORDER BY id ASC").fetchall()
    assert [row['transaction_hash'] for row in remaining] == ['0xold-sig']


def test_signal_repository_prune_keeps_rows_with_sim_orders(db_conn):
    old_iso = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()
    db_conn.execute(
        """
        INSERT INTO leader_trades (
            wallet, leader_name, transaction_hash, condition_id, asset_id, side,
            size, price, timestamp, market_title, market_slug, raw_json, ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ('0x1', 'alice', '0xsig1', 'cond1', 'asset1', 'BUY', 1.0, 0.5, old_iso, 'M1', 'm1', '{}', old_iso),
    )
    db_conn.execute(
        """
        INSERT INTO leader_trades (
            wallet, leader_name, transaction_hash, condition_id, asset_id, side,
            size, price, timestamp, market_title, market_slug, raw_json, ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ('0x2', 'bob', '0xsig2', 'cond2', 'asset2', 'BUY', 1.0, 0.5, old_iso, 'M2', 'm2', '{}', old_iso),
    )
    t1 = db_conn.execute("SELECT id FROM leader_trades WHERE transaction_hash='0xsig1'").fetchone()[0]
    t2 = db_conn.execute("SELECT id FROM leader_trades WHERE transaction_hash='0xsig2'").fetchone()[0]
    db_conn.execute(
        """
        INSERT INTO signals (
            leader_trade_id, wallet, leader_name, condition_id, asset_id, market_slug, side,
            leader_price, decision, reason, detected_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (t1, '0x1', 'alice', 'cond1', 'asset1', 'm1', 'BUY', 0.5, 'accepted', 'accepted', old_iso, '{}'),
    )
    db_conn.execute(
        """
        INSERT INTO signals (
            leader_trade_id, wallet, leader_name, condition_id, asset_id, market_slug, side,
            leader_price, decision, reason, detected_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (t2, '0x2', 'bob', 'cond2', 'asset2', 'm2', 'BUY', 0.5, 'accepted', 'accepted', old_iso, '{}'),
    )
    signal_keep_id = db_conn.execute("SELECT id FROM signals WHERE wallet='0x2'").fetchone()[0]
    db_conn.execute(
        """
        INSERT INTO sim_orders (
            signal_id, condition_id, asset_id, market_slug, side,
            requested_notional, filled_notional, filled_shares, fill_price, leader_price, slippage_pct,
            status, reason, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (signal_keep_id, 'cond2', 'asset2', 'm2', 'BUY', '10.00', '10.00', '20.000000', '0.500000', '0.500000', '0.0000', 'filled', 'filled', now_iso),
    )
    db_conn.commit()

    signal_repo = SignalRepository(db_conn)
    pruned = signal_repo.prune_older_than((datetime.now(timezone.utc) - timedelta(days=30)).isoformat())
    assert pruned == 1
    remaining = db_conn.execute("SELECT wallet FROM signals ORDER BY id ASC").fetchall()
    assert [row['wallet'] for row in remaining] == ['0x2']


def test_signal_repository_prune_keeps_rows_linked_to_open_positions(db_conn):
    old_iso = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    db_conn.execute(
        """
        INSERT INTO leader_trades (
            wallet, leader_name, transaction_hash, condition_id, asset_id, side,
            size, price, timestamp, market_title, market_slug, raw_json, ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ('0x3', 'carol', '0xsig-pos', 'cond-pos', 'asset-pos', 'BUY', 1.0, 0.5, old_iso, 'MP', 'mp', '{}', old_iso),
    )
    trade_id = db_conn.execute("SELECT id FROM leader_trades WHERE transaction_hash='0xsig-pos'").fetchone()[0]
    db_conn.execute(
        """
        INSERT INTO signals (
            leader_trade_id, wallet, leader_name, condition_id, asset_id, market_slug, side,
            leader_price, decision, reason, detected_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (trade_id, '0x3', 'carol', 'cond-pos', 'asset-pos', 'mp', 'BUY', 0.5, 'accepted', 'accepted', old_iso, '{}'),
    )
    db_conn.execute(
        """
        INSERT INTO positions (
            condition_id, asset_id, market_slug, side, shares, avg_cost, cost_basis, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ('cond-pos', 'asset-pos', 'mp', 'BUY', '10.000000', '0.500000', '5.00', datetime.now(timezone.utc).isoformat()),
    )
    db_conn.commit()

    signal_repo = SignalRepository(db_conn)
    pruned = signal_repo.prune_older_than((datetime.now(timezone.utc) - timedelta(days=30)).isoformat())
    assert pruned == 0
    remaining = db_conn.execute("SELECT wallet FROM signals ORDER BY id ASC").fetchall()
    assert [row['wallet'] for row in remaining] == ['0x3']


def test_job_run_repository_prune_older_than(db_conn):
    repo = JobRunRepository(db_conn)
    old_id = repo.start('old-job')
    new_id = repo.start('new-job')
    repo.finish(old_id, status='completed')
    repo.finish(new_id, status='completed')
    old_iso = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    db_conn.execute("UPDATE job_runs SET started_at = ? WHERE id = ?", (old_iso, old_id))
    db_conn.commit()

    pruned = repo.prune_older_than((datetime.now(timezone.utc) - timedelta(days=30)).isoformat())
    assert pruned == 1
    rows = db_conn.execute("SELECT id FROM job_runs ORDER BY id ASC").fetchall()
    assert [row['id'] for row in rows] == [new_id]
