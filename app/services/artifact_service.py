from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _reports_dir(project_root: str | Path | None) -> Path:
    root = Path(project_root) if project_root is not None else Path.cwd()
    path = root / '.scarf' / 'reports'
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_json(path: Path, payload: dict[str, Any]) -> str:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')
    return str(path)


def write_latest_summary(report: dict[str, Any], *, project_root: str | Path | None = None) -> dict[str, str]:
    report_dir = _reports_dir(project_root)
    md_path = report_dir / 'latest-summary.md'
    json_path = report_dir / 'latest-summary.json'
    markdown = f'''# Latest Trade Follow Summary

- Snapshot ID: {report.get("snapshot_id")}
- Snapshot Count: {report.get("snapshot_count")}
- Captured At: {report.get("captured_at")}
- Total Equity: {report.get("total_equity")}
- Unrealized PnL: {report.get("total_unrealized_pnl")}
- Realized PnL: {report.get("total_realized_pnl")}
- Open Positions: {report.get("open_position_count")}
- Accepted Signals: {report.get("accepted_signal_count")}
- Filled Orders: {report.get("filled_order_count")}
- Rejected Orders: {report.get("rejected_order_count")}
'''
    md_path.write_text(markdown, encoding='utf-8')
    return {
        'report_markdown_path': str(md_path),
        'report_json_path': _write_json(json_path, report),
    }


def write_performance_review(report: dict[str, Any], *, project_root: str | Path | None = None) -> dict[str, str]:
    report_dir = _reports_dir(project_root)
    md_path = report_dir / 'performance-review.md'
    json_path = report_dir / 'performance-review.json'
    markdown = f'''# 60-Day Review Notes

- Snapshot Count: {report.get("snapshot_count")}
- Period Start: {report.get("period_start")}
- Period End: {report.get("period_end")}
- Starting Equity: {report.get("starting_equity")}
- Ending Equity: {report.get("ending_equity")}
- Net PnL: {report.get("net_pnl")}
- Return %: {report.get("return_pct")}
- Max Drawdown %: {report.get("max_drawdown_pct")}
- Open Positions: {report.get("open_position_count")}
- Filled Orders: {report.get("filled_order_count")}
- Rejected Orders: {report.get("rejected_order_count")}
'''
    md_path.write_text(markdown, encoding='utf-8')
    return {
        'report_markdown_path': str(md_path),
        'report_json_path': _write_json(json_path, report),
    }


def append_detection_log(payload: dict[str, Any], *, project_root: str | Path | None = None, job_name: str = 'run-loop') -> str:
    report_dir = _reports_dir(project_root)
    path = report_dir / 'detection.log'
    line = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'job_name': job_name,
        'completed': payload.get('completed'),
        'iteration_count': payload.get('iteration_count'),
        'failed_step': payload.get('failed_step'),
    }
    with path.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(line, ensure_ascii=False) + '\n')
    return str(path)


def write_shadow_run(payload: dict[str, Any], *, project_root: str | Path | None = None) -> str:
    report_dir = _reports_dir(project_root)
    path = report_dir / 'shadow-run-latest.json'
    return _write_json(path, payload)


def write_auto_follow_gate(report: dict[str, Any], *, project_root: str | Path | None = None) -> dict[str, str]:
    report_dir = _reports_dir(project_root)
    md_path = report_dir / 'auto-follow-gate.md'
    json_path = report_dir / 'auto-follow-gate.json'
    status = report.get("status", "hold")
    markdown = f'''# Auto-Follow Gate

- Status: {status}
- Decision: {report.get("decision")}
- Generated At: {report.get("generated_at")}
- Window Hours: {report.get("window_hours")}
- Filled Orders (window): {report.get("filled_orders_window")}
- Accepted Signals (window): {report.get("accepted_signals_window")}
- Slippage Rejects (window): {report.get("slippage_rejects_window")}
- Slippage Reject Ratio: {report.get("slippage_reject_ratio")}
- Thresholds: {report.get("thresholds")}
- Notes: {report.get("notes")}
'''
    md_path.write_text(markdown, encoding='utf-8')
    return {
        'report_markdown_path': str(md_path),
        'report_json_path': _write_json(json_path, report),
    }
