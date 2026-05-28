from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing import Iterable

from app.domain.money import money, pct, price, shares as quantize_shares, to_float
from app.domain.models import Decision, Leader, LeaderTrade, MarketInfo, Side, SignalDecision, normalize_side, parse_datetime


def _decision_value(value: Decision | str) -> str:
    return value.value if isinstance(value, Decision) else str(value)


def _side_value(value: Side | str | None) -> str | None:
    normalized = normalize_side(value)
    if normalized is not None:
        return normalized.value
    return str(value) if value is not None else None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _money_text(value) -> str:
    return str(money(value))


def _price_text(value) -> str:
    return str(price(value))


def _shares_text(value) -> str:
    return str(quantize_shares(value))


def _pct_text(value) -> str:
    return str(pct(value))


def _decimal_text(value) -> str:
    return str(Decimal(str(value)))



class LeaderRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def has_any_leaders(self) -> bool:
        row = self.conn.execute("SELECT COUNT(*) AS c FROM leaders").fetchone()
        return bool(row["c"])

    def insert_many(self, leaders: Iterable[Leader], selection_run_id: str) -> int:
        inserted = 0
        for leader in leaders:
            cursor = self.conn.execute(
                """
                INSERT OR IGNORE INTO leaders (
                    rank, wallet, name, pseudonym, pnl_snapshot, volume_snapshot,
                    selection_run_id, selected_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    leader.rank,
                    leader.wallet,
                    leader.name,
                    leader.pseudonym,
                    leader.pnl_snapshot,
                    leader.volume_snapshot,
                    selection_run_id,
                    utc_now_iso(),
                    json.dumps(leader.raw_json or {}),
                ),
            )
            if cursor.rowcount > 0:
                inserted += 1

        self.conn.commit()
        return inserted

    def get_latest_selection_run_id(self) -> str | None:
        row = self.conn.execute(
            "SELECT selection_run_id FROM leaders ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return str(row["selection_run_id"]) if row is not None else None

    def get_latest_leaders(self) -> list[sqlite3.Row]:
        run_id = self.get_latest_selection_run_id()
        if run_id is None:
            return []
        return list(
            self.conn.execute(
                "SELECT * FROM leaders WHERE selection_run_id = ? ORDER BY rank ASC",
                (run_id,),
            ).fetchall()
        )


class LeaderTradeRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def insert_if_new(self, trade: LeaderTrade) -> bool:
        cursor = self.conn.execute(
            """
            INSERT OR IGNORE INTO leader_trades (
                wallet, leader_name, transaction_hash, condition_id, asset_id,
                side, size, price, timestamp, market_title, market_slug,
                raw_json, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade.wallet,
                trade.leader_name,
                trade.transaction_hash,
                trade.condition_id,
                trade.asset_id,
                trade.side,
                _shares_text(trade.size) if trade.size is not None else None,
                _price_text(trade.price) if trade.price is not None else None,
                trade.timestamp.isoformat(),
                trade.market_title,
                trade.market_slug,
                json.dumps(trade.raw_json),
                utc_now_iso(),
            ),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def count_all(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS c FROM leader_trades").fetchone()
        return int(row["c"])

    def list_without_signal(self, limit: int = 500) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT lt.*
                FROM leader_trades lt
                LEFT JOIN signals s ON s.leader_trade_id = lt.id
                WHERE s.id IS NULL
                ORDER BY lt.timestamp DESC, lt.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        )


class MarketRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get_by_condition_id(self, condition_id: str) -> MarketInfo | None:
        row = self.conn.execute(
            "SELECT * FROM markets WHERE condition_id = ?",
            (condition_id,),
        ).fetchone()
        if row is None:
            return None
        return MarketInfo(
            condition_id=str(row['condition_id']),
            title=row['title'],
            slug=row['slug'],
            end_time=parse_datetime(row['end_time']),
            liquidity=float(Decimal(str(row['liquidity']))) if row['liquidity'] is not None else None,
            active=bool(row['active']),
            closed=bool(row['closed']),
            yes_token_id=row['yes_token_id'],
            no_token_id=row['no_token_id'],
            yes_outcome=row['yes_outcome'],
            no_outcome=row['no_outcome'],
            raw_json=json.loads(row['raw_json']),
            refreshed_at=parse_datetime(row['refreshed_at']),
        )

    def upsert(self, market: MarketInfo) -> None:
        refreshed_at = market.refreshed_at.isoformat() if market.refreshed_at is not None else utc_now_iso()
        self.conn.execute(
            """
            INSERT INTO markets (
                condition_id, title, slug, end_time, liquidity,
                active, closed, yes_token_id, no_token_id,
                yes_outcome, no_outcome, raw_json, refreshed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(condition_id) DO UPDATE SET
                title=excluded.title,
                slug=excluded.slug,
                end_time=excluded.end_time,
                liquidity=excluded.liquidity,
                active=excluded.active,
                closed=excluded.closed,
                yes_token_id=excluded.yes_token_id,
                no_token_id=excluded.no_token_id,
                yes_outcome=excluded.yes_outcome,
                no_outcome=excluded.no_outcome,
                raw_json=excluded.raw_json,
                refreshed_at=excluded.refreshed_at
            """,
            (
                market.condition_id,
                market.title,
                market.slug,
                market.end_time.isoformat() if market.end_time is not None else None,
                _decimal_text(market.liquidity) if market.liquidity is not None else None,
                int(market.active),
                int(market.closed),
                market.yes_token_id,
                market.no_token_id,
                market.yes_outcome,
                market.no_outcome,
                json.dumps(market.raw_json),
                refreshed_at,
            ),
        )
        self.conn.commit()


class SignalRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def insert_if_new(self, trade: LeaderTrade, decision: SignalDecision) -> bool:
        cursor = self.conn.execute(
            """
            INSERT OR IGNORE INTO signals (
                leader_trade_id, wallet, leader_name, condition_id, asset_id,
                market_slug, side, leader_price, decision, reason,
                detected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision.leader_trade_id,
                trade.wallet,
                trade.leader_name,
                decision.condition_id,
                decision.asset_id,
                decision.market_slug,
                _side_value(decision.side),
                _price_text(decision.price) if decision.price is not None else None,
                _decision_value(decision.decision),
                decision.reason,
                utc_now_iso(),
                json.dumps(trade.raw_json),
            ),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def has_recent_accepted_signal(self, wallet: str, condition_id: str, asset_id: str, cooldown_minutes: int) -> bool:
        threshold = (datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes)).isoformat()
        row = self.conn.execute(
            """
            SELECT id FROM signals
            WHERE wallet = ? AND condition_id = ? AND asset_id = ?
              AND decision = 'accepted' AND detected_at >= ?
            ORDER BY id DESC LIMIT 1
            """,
            (wallet, condition_id, asset_id, threshold),
        ).fetchone()
        return row is not None

    def has_recent_accepted_market_signal(self, condition_id: str, asset_id: str, cooldown_minutes: int) -> bool:
        threshold = (datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes)).isoformat()
        row = self.conn.execute(
            """
            SELECT id FROM signals
            WHERE condition_id = ? AND asset_id = ?
              AND decision = 'accepted' AND detected_at >= ?
            ORDER BY id DESC LIMIT 1
            """,
            (condition_id, asset_id, threshold),
        ).fetchone()
        return row is not None

    def counts(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT decision, COUNT(*) AS c FROM signals GROUP BY decision"
        ).fetchall()
        return {str(r['decision']): int(r['c']) for r in rows}

    def list_pending_accepted(self, limit: int = 500) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT s.*
                FROM signals s
                LEFT JOIN sim_orders so ON so.signal_id = s.id
                WHERE s.decision = 'accepted' AND so.id IS NULL
                ORDER BY s.detected_at ASC, s.id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        )


class SimOrderRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def insert(
        self,
        signal_id: int,
        condition_id: str,
        asset_id: str,
        market_slug: str | None,
        side: str | None,
        requested_notional: float,
        filled_notional: float | None,
        filled_shares: float | None,
        fill_price: float | None,
        leader_price: float | None,
        slippage_pct: float | None,
        status: str,
        reason: str | None,
    ) -> int:
        return self._insert(
            signal_id=signal_id,
            condition_id=condition_id,
            asset_id=asset_id,
            market_slug=market_slug,
            side=side,
            requested_notional=requested_notional,
            filled_notional=filled_notional,
            filled_shares=filled_shares,
            fill_price=fill_price,
            leader_price=leader_price,
            slippage_pct=slippage_pct,
            status=status,
            reason=reason,
            commit=True,
        )

    def insert_in_tx(
        self,
        signal_id: int,
        condition_id: str,
        asset_id: str,
        market_slug: str | None,
        side: str | None,
        requested_notional: float,
        filled_notional: float | None,
        filled_shares: float | None,
        fill_price: float | None,
        leader_price: float | None,
        slippage_pct: float | None,
        status: str,
        reason: str | None,
    ) -> int:
        return self._insert(
            signal_id=signal_id,
            condition_id=condition_id,
            asset_id=asset_id,
            market_slug=market_slug,
            side=side,
            requested_notional=requested_notional,
            filled_notional=filled_notional,
            filled_shares=filled_shares,
            fill_price=fill_price,
            leader_price=leader_price,
            slippage_pct=slippage_pct,
            status=status,
            reason=reason,
            commit=False,
        )

    def _insert(
        self,
        *,
        signal_id: int,
        condition_id: str,
        asset_id: str,
        market_slug: str | None,
        side: str | None,
        requested_notional: float,
        filled_notional: float | None,
        filled_shares: float | None,
        fill_price: float | None,
        leader_price: float | None,
        slippage_pct: float | None,
        status: str,
        reason: str | None,
        commit: bool,
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO sim_orders (
                signal_id, condition_id, asset_id, market_slug, side,
                requested_notional, filled_notional, filled_shares, fill_price,
                leader_price, slippage_pct, status, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal_id, condition_id, asset_id, market_slug, side,
                _money_text(requested_notional),
                _money_text(filled_notional) if filled_notional is not None else None,
                _shares_text(filled_shares) if filled_shares is not None else None,
                _price_text(fill_price) if fill_price is not None else None,
                _price_text(leader_price) if leader_price is not None else None,
                _pct_text(slippage_pct) if slippage_pct is not None else None,
                status,
                reason,
                utc_now_iso(),
            ),
        )
        if commit:
            self.conn.commit()
        return int(cursor.lastrowid)

    def count_by_status(self, status: str) -> int:
        row = self.conn.execute(
            'SELECT COUNT(*) AS c FROM sim_orders WHERE status = ?',
            (status,),
        ).fetchone()
        return int(row['c']) if row is not None else 0

    def count_filled_since(self, since_iso: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM sim_orders WHERE status = 'filled' AND created_at >= ?",
            (since_iso,),
        ).fetchone()
        return int(row['c']) if row is not None else 0


@dataclass
class Position:
    condition_id: str
    asset_id: str
    market_slug: str | None
    side: str | None
    shares: float
    avg_cost: float
    cost_basis: float


@dataclass
class PortfolioSnapshot:
    id: int
    captured_at: datetime
    total_cost_basis: float
    total_market_value: float
    total_unrealized_pnl: float
    total_realized_pnl: float
    total_equity: float
    drawdown_pct: float
    raw_json: dict


class JobRunRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def start(self, job_name: str) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO job_runs (job_name, started_at, status, inserted_count, skipped_count)
            VALUES (?, ?, 'running', 0, 0)
            """,
            (job_name, utc_now_iso()),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def finish(
        self,
        job_run_id: int,
        *,
        status: str,
        inserted_count: int = 0,
        skipped_count: int = 0,
        error_message: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE job_runs
            SET finished_at = ?, status = ?, inserted_count = ?, skipped_count = ?, error_message = ?
            WHERE id = ?
            """,
            (utc_now_iso(), status, inserted_count, skipped_count, error_message, job_run_id),
        )
        self.conn.commit()


class PositionRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, condition_id: str, asset_id: str) -> Position | None:
        row = self.conn.execute(
            "SELECT * FROM positions WHERE condition_id = ? AND asset_id = ?",
            (condition_id, asset_id),
        ).fetchone()
        if row is None:
            return None
        return Position(
            condition_id=str(row['condition_id']),
            asset_id=str(row['asset_id']),
            market_slug=row['market_slug'],
            side=row['side'],
            shares=to_float(quantize_shares(row['shares'])),
            avg_cost=to_float(price(row['avg_cost'])),
            cost_basis=to_float(money(row['cost_basis'])),
        )

    def current_cost_basis(self, condition_id: str, asset_id: str) -> float:
        pos = self.get(condition_id, asset_id)
        return pos.cost_basis if pos is not None else 0.0

    def current_market_cost_basis(self, condition_id: str) -> float:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(cost_basis), '0.00') AS total FROM positions WHERE condition_id = ?",
            (condition_id,),
        ).fetchone()
        if row is None:
            return 0.0
        return to_float(money(row['total']))

    def total_cost_basis(self) -> float:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(cost_basis), '0.00') AS total FROM positions"
        ).fetchone()
        return to_float(money(row['total'])) if row is not None else 0.0

    def list_all(self) -> list[Position]:
        return [
            Position(
                condition_id=str(row['condition_id']),
                asset_id=str(row['asset_id']),
                market_slug=row['market_slug'],
                side=row['side'],
                shares=to_float(quantize_shares(row['shares'])),
                avg_cost=to_float(price(row['avg_cost'])),
                cost_basis=to_float(money(row['cost_basis'])),
            )
            for row in self.conn.execute('SELECT * FROM positions ORDER BY id ASC').fetchall()
        ]

    def upsert_buy(self, condition_id: str, asset_id: str, market_slug: str | None, side: str | None, shares: float, fill_price: float, *, commit: bool = True) -> None:
        existing = self.get(condition_id, asset_id)
        share_qty = shares if isinstance(shares, Decimal) else quantize_shares(shares)
        fill_price_dec = price(fill_price)
        add_cost = money(share_qty * fill_price_dec)
        if existing is None:
            self.conn.execute(
                """
                INSERT INTO positions (
                    condition_id, asset_id, market_slug, side, shares, avg_cost, cost_basis, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (condition_id, asset_id, market_slug, side, _shares_text(share_qty), _price_text(fill_price_dec), _money_text(add_cost), utc_now_iso()),
            )
        else:
            new_shares = quantize_shares(existing.shares) + share_qty
            new_cost = money(Decimal(str(existing.cost_basis)) + add_cost)
            new_avg = price(new_cost / new_shares) if new_shares else price(0)
            self.conn.execute(
                """
                UPDATE positions
                SET market_slug = ?, side = ?, shares = ?, avg_cost = ?, cost_basis = ?, updated_at = ?
                WHERE condition_id = ? AND asset_id = ?
                """,
                (market_slug, side, _shares_text(new_shares), _price_text(new_avg), _money_text(new_cost), utc_now_iso(), condition_id, asset_id),
            )
        if commit:
            self.conn.commit()

    def delete(self, condition_id: str, asset_id: str, *, commit: bool = True) -> None:
        self.conn.execute(
            "DELETE FROM positions WHERE condition_id = ? AND asset_id = ?",
            (condition_id, asset_id),
        )
        if commit:
            self.conn.commit()


class PortfolioSnapshotRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def count(self) -> int:
        row = self.conn.execute('SELECT COUNT(*) AS c FROM portfolio_snapshots').fetchone()
        return int(row['c']) if row is not None else 0

    def first(self) -> PortfolioSnapshot | None:
        row = self.conn.execute(
            'SELECT * FROM portfolio_snapshots ORDER BY id ASC LIMIT 1'
        ).fetchone()
        return self._row_to_snapshot(row)

    def latest(self) -> PortfolioSnapshot | None:
        row = self.conn.execute(
            'SELECT * FROM portfolio_snapshots ORDER BY id DESC LIMIT 1'
        ).fetchone()
        return self._row_to_snapshot(row)

    def _row_to_snapshot(self, row: sqlite3.Row | None) -> PortfolioSnapshot | None:
        if row is None:
            return None
        return PortfolioSnapshot(
            id=int(row['id']),
            captured_at=parse_datetime(row['captured_at']) or datetime.now(timezone.utc),
            total_cost_basis=to_float(money(row['total_cost_basis'])),
            total_market_value=to_float(money(row['total_market_value'])),
            total_unrealized_pnl=to_float(money(row['total_unrealized_pnl'])),
            total_realized_pnl=to_float(money(row['total_realized_pnl'])),
            total_equity=to_float(money(row['total_equity'])),
            drawdown_pct=to_float(pct(row['drawdown_pct'])),
            raw_json=json.loads(row['raw_json']) if row['raw_json'] else {},
        )

    def max_drawdown_pct(self) -> float:
        row = self.conn.execute('SELECT MAX(CAST(drawdown_pct AS REAL)) AS max_drawdown FROM portfolio_snapshots').fetchone()
        return to_float(pct(row['max_drawdown'])) if row is not None and row['max_drawdown'] is not None else 0.0

    def compute_drawdown_pct(self, total_equity: float) -> float:
        row = self.conn.execute('SELECT MAX(CAST(total_equity AS REAL)) AS peak FROM portfolio_snapshots').fetchone()
        peak = to_float(money(row['peak'])) if row is not None and row['peak'] is not None else total_equity
        if peak <= 0:
            return 0.0
        if total_equity >= peak:
            return 0.0
        return to_float(pct(((peak - total_equity) / peak) * 100.0))

    def insert(self, *, total_cost_basis: float, total_market_value: float, total_unrealized_pnl: float, total_realized_pnl: float, total_equity: float, drawdown_pct: float, raw_json: dict, commit: bool = True) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO portfolio_snapshots (
                captured_at, total_cost_basis, total_market_value,
                total_unrealized_pnl, total_realized_pnl, total_equity, drawdown_pct, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                utc_now_iso(),
                _money_text(total_cost_basis),
                _money_text(total_market_value),
                _money_text(total_unrealized_pnl),
                _money_text(total_realized_pnl),
                _money_text(total_equity),
                _pct_text(drawdown_pct),
                json.dumps(raw_json),
            ),
        )
        if commit:
            self.conn.commit()
        return int(cursor.lastrowid)
