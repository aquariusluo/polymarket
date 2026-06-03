from __future__ import annotations

import json

from app.config import Settings, get_settings
from app.domain.models import Decision, LeaderTrade, SignalDecision
from app.services.job_run_service import execute_job
from app.services.market_service import MarketService
from app.services.signal_service import SignalService
from app.storage.db import get_connection, init_db
from app.storage.repositories import SignalRepository, SimOrderRepository


def run(
    settings: Settings | None = None,
    *,
    project_root=None,
    market_service_cls=MarketService,
    signal_service_cls=SignalService,
    conn=None,
) -> dict:
    settings = settings or get_settings(project_root)

    def runner(conn) -> dict:
        market_service = market_service_cls(conn, settings)
        signal_service = signal_service_cls(conn, settings, market_service=market_service)
        signal_repo = SignalRepository(conn)
        order_repo = SimOrderRepository(conn)

        checked = 0
        reclassified = 0
        sim_orders_deleted = 0
        reason_normalized = 0

        for row in signal_repo.list_recheckable_accepted():
            checked += 1
            trade = LeaderTrade.from_row(row)
            signal_id = int(row['signal_id'])
            signal_raw_json = row['signal_raw_json']
            if not isinstance(signal_raw_json, dict):
                signal_raw_json = json.loads(signal_raw_json) if signal_raw_json else {}
            decision = SignalDecision(
                leader_trade_id=int(row['id']),
                condition_id=str(row['signal_condition_id']),
                asset_id=str(row['signal_asset_id']),
                decision=Decision.ACCEPTED,
                reason='accepted',
                side=row['signal_side'],
                price=float(row['signal_leader_price']) if row['signal_leader_price'] is not None else trade.price,
                market_slug=row['signal_market_slug'],
            )
            reason = signal_service.copyability_rejection_reason(trade, decision, signal_raw_json=signal_raw_json)
            if reason is None and order_repo.has_rejected_reason(signal_id, 'slippage_too_high'):
                reason = 'book_slippage_too_high'
            if reason is None:
                continue
            signal_repo.reclassify(signal_id, decision=Decision.REJECTED, reason=reason, commit=False)
            sim_orders_deleted += order_repo.delete_rejected_for_signal(signal_id, commit=False)
            reclassified += 1

        for row in signal_repo.list_rejected_by_reason('book_slippage_too_high'):
            checked += 1
            trade = LeaderTrade.from_row(row)
            signal_raw_json = row['signal_raw_json']
            if not isinstance(signal_raw_json, dict):
                signal_raw_json = json.loads(signal_raw_json) if signal_raw_json else {}
            decision = SignalDecision(
                leader_trade_id=int(row['id']),
                condition_id=str(row['signal_condition_id']),
                asset_id=str(row['signal_asset_id']),
                decision=Decision.ACCEPTED,
                reason='accepted',
                side=row['signal_side'],
                price=float(row['signal_leader_price']) if row['signal_leader_price'] is not None else trade.price,
                market_slug=row['signal_market_slug'],
            )
            reason = signal_service.copyability_rejection_reason(trade, decision, signal_raw_json=signal_raw_json)
            if reason != 'book_spread_too_wide':
                continue
            signal_repo.reclassify(int(row['signal_id']), decision=Decision.REJECTED, reason=reason, commit=False)
            reason_normalized += 1

        return {
            'checked': checked,
            'reclassified': reclassified,
            'reason_normalized': reason_normalized,
            'sim_orders_deleted': sim_orders_deleted,
            'inserted': reclassified,
            'skipped': checked - reclassified - reason_normalized,
        }

    if conn is not None:
        return execute_job(conn, job_name='backfill-signals', runner=runner, atomic=True)
    with get_connection(settings.db_path) as own_conn:
        init_db(settings.db_path, conn=own_conn)
        return execute_job(own_conn, job_name='backfill-signals', runner=runner, atomic=True)
