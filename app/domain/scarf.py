from __future__ import annotations

from datetime import date, datetime, timezone

from app.config import ScarfConfig


def compute_evaluation_verdict(scarf: ScarfConfig, total_equity: float) -> tuple[str, str]:
    start_raw = scarf.evaluation_start_date or ''
    days_target = int(scarf.evaluation_days or 60)
    if not start_raw:
        return 'pending', 'No evaluation start date configured'
    try:
        start_date = date.fromisoformat(start_raw)
    except ValueError:
        return 'pending', 'Invalid evaluation start date'
    elapsed_days = (datetime.now(timezone.utc).date() - start_date).days
    if elapsed_days < days_target:
        return 'tracking', f'{elapsed_days}/{days_target} days elapsed'
    if total_equity > 0:
        return 'matured_profitable', f'Matured after {elapsed_days} days with positive equity'
    if total_equity < 0:
        return 'matured_unprofitable', f'Matured after {elapsed_days} days with negative equity'
    return 'matured_flat', f'Matured after {elapsed_days} days with flat equity'
