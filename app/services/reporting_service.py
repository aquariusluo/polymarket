from __future__ import annotations

import sqlite3

from app.config import Settings
from app.storage.repositories import PortfolioSnapshotRepository, PositionRepository, SignalRepository, SimOrderRepository


class ReportingService:
    def __init__(self, conn: sqlite3.Connection, settings: Settings):
        self.conn = conn
        self.settings = settings
        self.snapshot_repo = PortfolioSnapshotRepository(conn)
        self.position_repo = PositionRepository(conn)
        self.signal_repo = SignalRepository(conn)
        self.order_repo = SimOrderRepository(conn)

    def _accepted_signal_count(self) -> int:
        return int(self.signal_repo.counts().get('accepted', 0))

    def _open_position_count(self) -> int:
        return sum(1 for position in self.position_repo.list_all() if position.shares > 0)

    def generate_daily_report(self) -> dict:
        snapshot = self.snapshot_repo.latest()
        if snapshot is None:
            raise RuntimeError('no portfolio snapshots found')
        return {
            'snapshot_id': snapshot.id,
            'snapshot_count': self.snapshot_repo.count(),
            'captured_at': snapshot.captured_at.isoformat(),
            'total_cost_basis': snapshot.total_cost_basis,
            'total_market_value': snapshot.total_market_value,
            'total_unrealized_pnl': snapshot.total_unrealized_pnl,
            'total_realized_pnl': snapshot.total_realized_pnl,
            'total_equity': snapshot.total_equity,
            'drawdown_pct': snapshot.drawdown_pct,
            'open_position_count': self._open_position_count(),
            'accepted_signal_count': self._accepted_signal_count(),
            'filled_order_count': self.order_repo.count_by_status('filled'),
            'rejected_order_count': self.order_repo.count_by_status('rejected'),
        }

    def generate_final_report(self) -> dict:
        latest = self.snapshot_repo.latest()
        if latest is None:
            raise RuntimeError('no portfolio snapshots found')
        first = self.snapshot_repo.first()
        if first is None:
            raise RuntimeError('no portfolio snapshots found')

        starting_equity = first.total_equity
        ending_equity = latest.total_equity
        net_pnl = ending_equity - starting_equity
        return_pct = 0.0 if starting_equity == 0 else (net_pnl / starting_equity) * 100.0
        return {
            'snapshot_count': self.snapshot_repo.count(),
            'period_start': first.captured_at.isoformat(),
            'period_end': latest.captured_at.isoformat(),
            'starting_equity': starting_equity,
            'ending_equity': ending_equity,
            'net_pnl': net_pnl,
            'return_pct': return_pct,
            'max_drawdown_pct': self.snapshot_repo.max_drawdown_pct(),
            'open_position_count': self._open_position_count(),
            'filled_order_count': self.order_repo.count_by_status('filled'),
            'rejected_order_count': self.order_repo.count_by_status('rejected'),
            'accepted_signal_count': self._accepted_signal_count(),
        }
