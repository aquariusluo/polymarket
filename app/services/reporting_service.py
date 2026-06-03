from __future__ import annotations

import sqlite3

from app.config import Settings
from app.storage.repositories import PortfolioSnapshotRepository, PositionRepository, SignalRepository, SimOrderRepository


class ReportingService:
    UNIVERSE_QUALITY_REASONS = (
        'market_unsupported',
        'too_close_to_expiry',
        'market_inactive_or_closed',
        'liquidity_below_threshold',
        'asset_not_in_market_tokens',
    )
    STRUCTURAL_COPYABILITY_PROXY_REASONS = (
        'book_slippage_too_high',
        'book_spread_too_wide',
        'no_copyable_ask',
        'market_unavailable',
    )
    FAILURE_SIGNAL_EVIDENCE_CATEGORIES = (
        'universe_quality',
        'copyability',
    )
    REASON_CATEGORY_SQL = """
        CASE reason
            WHEN 'wallet_excluded' THEN 'wallet_filter'
            WHEN 'market_unsupported' THEN 'market_lookup'
            WHEN 'too_close_to_expiry' THEN 'universe_quality'
            WHEN 'market_inactive_or_closed' THEN 'universe_quality'
            WHEN 'liquidity_below_threshold' THEN 'universe_quality'
            WHEN 'asset_not_in_market_tokens' THEN 'universe_quality'
            WHEN 'trade_too_old' THEN 'eligibility'
            WHEN 'side_not_buy' THEN 'eligibility'
            WHEN 'book_spread_too_wide' THEN 'copyability'
            WHEN 'book_slippage_too_high' THEN 'copyability'
            WHEN 'no_copyable_ask' THEN 'copyability'
            WHEN 'market_unavailable' THEN 'copyability'
            WHEN 'cooldown_duplicate_signal' THEN 'cooldown'
            WHEN 'cooldown_duplicate_market_signal' THEN 'cooldown'
            WHEN 'accepted' THEN 'accepted'
            ELSE 'other'
        END
    """

    def __init__(self, conn: sqlite3.Connection, settings: Settings):
        self.conn = conn
        self.settings = settings
        self.snapshot_repo = PortfolioSnapshotRepository(conn)
        self.position_repo = PositionRepository(conn)
        self.signal_repo = SignalRepository(conn)
        self.order_repo = SimOrderRepository(conn)

    def _accepted_signal_count(self) -> int:
        return int(self.signal_repo.counts().get('accepted', 0))

    def _signal_rejection_reasons(self) -> dict[str, int]:
        rows = self.conn.execute(
            """
            SELECT reason, COUNT(*) AS c
            FROM signals
            WHERE decision = 'rejected' AND reason IS NOT NULL AND reason != ''
            GROUP BY reason
            ORDER BY c DESC, reason ASC
            """
        ).fetchall()
        return {str(row['reason']): int(row['c']) for row in rows}

    def _execution_rejection_reasons(self) -> dict[str, int]:
        rows = self.conn.execute(
            """
            SELECT reason, COUNT(*) AS c
            FROM sim_orders
            WHERE status = 'rejected' AND reason IS NOT NULL AND reason != ''
            GROUP BY reason
            ORDER BY c DESC, reason ASC
            """
        ).fetchall()
        return {str(row['reason']): int(row['c']) for row in rows}

    def _execution_suppression_reasons(self) -> dict[str, int]:
        rows = self.conn.execute(
            """
            SELECT reason, COUNT(*) AS c
            FROM sim_orders
            WHERE status = 'suppressed' AND reason IS NOT NULL AND reason != ''
            GROUP BY reason
            ORDER BY c DESC, reason ASC
            """
        ).fetchall()
        return {str(row['reason']): int(row['c']) for row in rows}

    def _open_position_count(self) -> int:
        return sum(1 for position in self.position_repo.list_all() if position.shares > 0)

    def _total_signal_count(self) -> int:
        row = self.conn.execute('SELECT COUNT(*) AS c FROM signals').fetchone()
        return int(row['c']) if row is not None else 0

    def _rejected_signal_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS c FROM signals WHERE decision = 'rejected'").fetchone()
        return int(row['c']) if row is not None else 0

    def _snapshot_coverage_count(self) -> int:
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM signals
            WHERE json_extract(raw_json, '$.copyability.asset_id') IS NOT NULL
            """
        ).fetchone()
        return int(row['c']) if row is not None else 0

    def _sim_order_coverage_count(self) -> int:
        row = self.conn.execute('SELECT COUNT(*) AS c FROM sim_orders').fetchone()
        return int(row['c']) if row is not None else 0

    def _reason_counts_for(self, reasons: tuple[str, ...]) -> dict[str, int]:
        placeholders = ', '.join('?' for _ in reasons)
        rows = self.conn.execute(
            f"""
            SELECT reason, COUNT(*) AS c
            FROM signals
            WHERE decision = 'rejected'
              AND reason IN ({placeholders})
            GROUP BY reason
            ORDER BY c DESC, reason ASC
            """,
            reasons,
        ).fetchall()
        return {str(row['reason']): int(row['c']) for row in rows}

    def _signal_evidence_counts(self) -> dict[str, dict[str, int]]:
        rows = self.conn.execute(
            f"""
            WITH normalized AS (
                SELECT
                    COALESCE(
                        NULLIF(json_extract(raw_json, '$.signal_evidence.stage'), ''),
                        CASE
                            WHEN reason = 'wallet_excluded' THEN 'wallet_filter'
                            WHEN reason = 'market_unsupported' THEN 'market_lookup'
                            WHEN reason IN (
                                'cooldown_duplicate_signal',
                                'cooldown_duplicate_market_signal'
                            ) THEN 'cooldown'
                            WHEN reason IN (
                                'book_spread_too_wide',
                                'book_slippage_too_high',
                                'no_copyable_ask',
                                'market_unavailable'
                            ) THEN 'copyability'
                            WHEN decision = 'accepted' THEN 'copyability'
                            ELSE 'trade_filter'
                        END
                    ) AS stage,
                    COALESCE(
                        NULLIF(json_extract(raw_json, '$.signal_evidence.category'), ''),
                        {self.REASON_CATEGORY_SQL}
                    ) AS category
                FROM signals
            )
            SELECT stage, category, COUNT(*) AS c
            FROM normalized
            WHERE stage IS NOT NULL
              AND stage != ''
              AND category IS NOT NULL
              AND category != ''
            GROUP BY stage, category
            ORDER BY stage ASC, c DESC, category ASC
            """
        ).fetchall()

        counts: dict[str, dict[str, int]] = {}
        for row in rows:
            stage = str(row['stage'])
            category = str(row['category'])
            counts.setdefault(stage, {})[category] = int(row['c'])
        return counts

    def _rejected_failure_evidence_count(self) -> int:
        row = self.conn.execute(
            f"""
            WITH normalized AS (
                SELECT
                    COALESCE(
                        NULLIF(json_extract(raw_json, '$.signal_evidence.category'), ''),
                        {self.REASON_CATEGORY_SQL}
                    ) AS category
                FROM signals
                WHERE decision = 'rejected'
            )
            SELECT COUNT(*) AS c
            FROM normalized
            WHERE category IN ({', '.join('?' for _ in self.FAILURE_SIGNAL_EVIDENCE_CATEGORIES)})
            """,
            self.FAILURE_SIGNAL_EVIDENCE_CATEGORIES,
        ).fetchone()
        return int(row['c']) if row is not None else 0

    def generate_shadow_evidence_report(self) -> dict:
        latest_snapshot = self.snapshot_repo.latest()
        total_signals = self._total_signal_count()
        rejected_signals = self._rejected_signal_count()
        snapshot_coverage_count = self._snapshot_coverage_count()
        sim_order_coverage_count = self._sim_order_coverage_count()
        filled_order_count = self.order_repo.count_by_status('filled')
        universe_quality = self._reason_counts_for(self.UNIVERSE_QUALITY_REASONS)
        structural_copyability_proxies = self._reason_counts_for(self.STRUCTURAL_COPYABILITY_PROXY_REASONS)
        signal_evidence_counts = self._signal_evidence_counts()
        rejected_failure_evidence_count = self._rejected_failure_evidence_count()

        universe_reject_count = sum(universe_quality.values())
        tradable_candidate_count = max(total_signals - universe_reject_count, 0)

        total_signals_safe = total_signals or 1
        tradable_universe_share = tradable_candidate_count / total_signals_safe
        snapshot_coverage_rate = snapshot_coverage_count / total_signals_safe
        sim_order_coverage_rate = sim_order_coverage_count / total_signals_safe

        limitations: list[str] = []
        if total_signals == 0:
            limitations.append('No signals are present in the current primary database yet.')
        if snapshot_coverage_count == 0:
            limitations.append('No detection-time copyability snapshots are present in the current primary database.')
        if sim_order_coverage_count == 0:
            limitations.append('No sim-order rows are present, so execution-stage and economic-copyability conclusions are not available yet.')
        elif filled_order_count == 0:
            limitations.append('Sim-order rows exist, but none have filled yet.')
        if tradable_candidate_count == 0:
            limitations.append('No candidates remain after the current universe-quality rejection filters.')

        if total_signals == 0:
            verdict = 'unclear'
        elif (
            rejected_signals == total_signals
            and total_signals > 0
            and snapshot_coverage_count == 0
            and sim_order_coverage_count == 0
            and rejected_failure_evidence_count == rejected_signals
        ):
            verdict = 'failing'
        elif tradable_universe_share < 0.05 and snapshot_coverage_count == 0 and sim_order_coverage_count == 0:
            verdict = 'failing'
        elif snapshot_coverage_count == 0 or sim_order_coverage_count == 0 or filled_order_count == 0:
            verdict = 'unclear'
        else:
            verdict = 'promising'

        return {
            'generated_at': latest_snapshot.captured_at.isoformat() if latest_snapshot is not None else None,
            'strategy_verdict': verdict,
            'total_signal_count': total_signals,
            'rejected_signal_count': rejected_signals,
            'snapshot_coverage_count': snapshot_coverage_count,
            'snapshot_coverage_rate': round(snapshot_coverage_rate, 4),
            'sim_order_coverage_count': sim_order_coverage_count,
            'sim_order_coverage_rate': round(sim_order_coverage_rate, 4),
            'tradable_candidate_count': tradable_candidate_count,
            'tradable_universe_share': round(tradable_universe_share, 4),
            'universe_quality_reasons': universe_quality,
            'structural_copyability_proxy_reasons': structural_copyability_proxies,
            'signal_evidence_counts': signal_evidence_counts,
            'limitations': limitations,
        }

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
            'signal_rejection_reasons': self._signal_rejection_reasons(),
            'execution_rejection_reasons': self._execution_rejection_reasons(),
            'execution_suppression_reasons': self._execution_suppression_reasons(),
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
            'signal_rejection_reasons': self._signal_rejection_reasons(),
            'execution_rejection_reasons': self._execution_rejection_reasons(),
            'execution_suppression_reasons': self._execution_suppression_reasons(),
        }
