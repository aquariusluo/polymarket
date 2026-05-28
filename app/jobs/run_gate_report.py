from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config import Settings, get_settings
from app.services.artifact_service import write_auto_follow_gate
from app.storage.db import get_connection, init_db


def _count(conn, query: str, params: tuple) -> int:
    row = conn.execute(query, params).fetchone()
    return int(row[0]) if row is not None else 0


def _count_distinct(conn, query: str, params: tuple) -> int:
    row = conn.execute(query, params).fetchone()
    return int(row[0]) if row is not None else 0


def run(settings: Settings | None = None, *, project_root=None, window_hours: int = 72) -> dict:
    settings = settings or get_settings(project_root)
    init_db(settings.db_path)

    now = datetime.now(timezone.utc)
    since = (now - timedelta(hours=window_hours)).isoformat()

    with get_connection(settings.db_path) as conn:
        filled_orders = _count(
            conn,
            "SELECT COUNT(*) FROM sim_orders WHERE status = 'filled' AND created_at >= ?",
            (since,),
        )
        accepted_signals = _count(
            conn,
            "SELECT COUNT(*) FROM signals WHERE decision = 'accepted' AND detected_at >= ?",
            (since,),
        )
        rejected_orders = _count(
            conn,
            "SELECT COUNT(*) FROM sim_orders WHERE status = 'rejected' AND created_at >= ?",
            (since,),
        )
        slippage_rejects = _count(
            conn,
            "SELECT COUNT(*) FROM sim_orders WHERE status = 'rejected' AND reason = 'slippage_too_high' AND created_at >= ?",
            (since,),
        )
        unique_markets = _count_distinct(
            conn,
            "SELECT COUNT(DISTINCT condition_id) FROM sim_orders WHERE status = 'filled' AND created_at >= ?",
            (since,),
        )

        realized_pnl = 0.0
        max_drawdown = 0.0
        snapshot_row = conn.execute(
            'SELECT total_realized_pnl FROM portfolio_snapshots ORDER BY id DESC LIMIT 1'
        ).fetchone()
        if snapshot_row:
            realized_pnl = float(dict(snapshot_row).get('total_realized_pnl', 0))

        dd_row = conn.execute('SELECT MAX(drawdown_pct) FROM portfolio_snapshots').fetchone()
        if dd_row and dd_row[0] is not None:
            max_drawdown = float(dd_row[0])

    slippage_ratio = (slippage_rejects / rejected_orders) if rejected_orders > 0 else 0.0

    thresholds = {
        "min_filled_orders_window": 10,
        "max_accept_to_fill_ratio": 4,
        "max_slippage_reject_ratio": 0.6,
        "max_drawdown_pct": 10.0,
        "min_unique_markets": 3,
    }

    status = "hold"
    notes: list[str] = []

    if filled_orders < thresholds["min_filled_orders_window"]:
        notes.append(
            f"Only {filled_orders} fills in {window_hours}h window (need >= {thresholds['min_filled_orders_window']})."
        )
    elif filled_orders > 0 and (accepted_signals / filled_orders) > thresholds["max_accept_to_fill_ratio"]:
        ratio = round(accepted_signals / filled_orders, 1)
        notes.append(
            f"Accept-to-fill ratio is {ratio} (max {thresholds['max_accept_to_fill_ratio']})."
        )

    if rejected_orders > 0 and slippage_ratio > thresholds["max_slippage_reject_ratio"]:
        notes.append(
            f"Slippage rejects at {slippage_ratio:.1%} of rejections (max {thresholds['max_slippage_reject_ratio']:.0%})."
        )

    if realized_pnl < 0:
        notes.append(f"Simulated realized PnL is negative (${realized_pnl:,.2f}).")

    if unique_markets < thresholds["min_unique_markets"] and filled_orders > 0:
        notes.append(
            f"Fills concentrated in {unique_markets} market(s) (need >= {thresholds['min_unique_markets']} unique)."
        )

    if max_drawdown > thresholds["max_drawdown_pct"]:
        notes.append(
            f"Max drawdown at {max_drawdown:.1f}% exceeds {thresholds['max_drawdown_pct']}% limit."
        )

    if not notes:
        status = "pass"
        decision = "auto_follow_candidate"
        notes.append("All gate conditions met in current window.")
    else:
        decision = "manual_confirm_only"

    report = {
        "status": status,
        "decision": decision,
        "generated_at": now.isoformat(),
        "window_hours": window_hours,
        "filled_orders_window": filled_orders,
        "accepted_signals_window": accepted_signals,
        "rejected_orders_window": rejected_orders,
        "slippage_rejects_window": slippage_rejects,
        "slippage_reject_ratio": round(slippage_ratio, 4),
        "unique_markets_window": unique_markets,
        "realized_pnl": realized_pnl,
        "max_drawdown_pct": round(max_drawdown, 1),
        "thresholds": thresholds,
        "notes": notes,
    }
    artifacts = write_auto_follow_gate(report, project_root=project_root)
    return {
        **report,
        **artifacts,
    }
