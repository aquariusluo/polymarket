from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config import Settings, get_settings
from app.services.artifact_service import write_auto_follow_gate
from app.storage.db import get_connection, init_db


def _count(conn, query: str, params: tuple) -> int:
    row = conn.execute(query, params).fetchone()
    return int(row[0]) if row is not None else 0


def run(settings: Settings | None = None, *, project_root=None, window_hours: int = 24) -> dict:
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

    slippage_ratio = (slippage_rejects / rejected_orders) if rejected_orders > 0 else 0.0

    thresholds = {
        "min_filled_orders_window": 3,
        "max_accept_to_fill_ratio": 3,
        "max_slippage_reject_ratio": 0.7,
    }

    status = "hold"
    notes: list[str] = []
    if filled_orders < thresholds["min_filled_orders_window"]:
        notes.append("Not enough filled samples in the recent window.")
    if accepted_signals > 0 and (accepted_signals / max(filled_orders, 1)) > thresholds["max_accept_to_fill_ratio"]:
        notes.append("Accepted-to-filled efficiency is still weak.")
    if rejected_orders > 0 and slippage_ratio > thresholds["max_slippage_reject_ratio"]:
        notes.append("Slippage rejects are still dominating rejected orders.")

    if not notes:
        status = "pass"
        decision = "auto_follow_candidate"
        notes.append("Gate conditions met in current window.")
    else:
        decision = "manual_confirm_only"

    report = {
        "status": status,
        "decision": decision,
        "generated_at": now.isoformat(),
        "window_hours": window_hours,
        "filled_orders_window": filled_orders,
        "accepted_signals_window": accepted_signals,
        "slippage_rejects_window": slippage_rejects,
        "slippage_reject_ratio": round(slippage_ratio, 4),
        "thresholds": thresholds,
        "notes": notes,
    }
    artifacts = write_auto_follow_gate(report, project_root=project_root)
    return {
        **report,
        **artifacts,
    }
