from __future__ import annotations

import sys

from app.jobs import (
    run_backfill_signals,
    run_daily_report,
    run_final_report,
    run_generate_signals,
    run_gate_report,
    run_mark_to_market,
    run_pipeline,
    run_poll_trades,
    run_prune_data,
    run_select_leaders,
    run_shadow,
    run_shadow_evidence,
    run_simulate,
)
from app.storage.db import decimal_storage_issues, get_connection, init_db
from app.config import get_settings


def _print_mapping(data: dict) -> None:
    for key, value in data.items():
        if key == 'steps':
            for step in value:
                print(f"step={step['name']} status={step['status']}")
                if 'result' in step:
                    for sub_key, sub_value in step['result'].items():
                        print(f"{step['name']}.{sub_key}={sub_value}")
                if 'error' in step:
                    print(f"{step['name']}.error={step['error']}")
        else:
            print(f"{key}={value}")


def cmd_init() -> None:
    settings = get_settings()
    init_db(settings.db_path)
    print(f"database initialized: {settings.db_path}")


def cmd_db_health() -> None:
    settings = get_settings()
    with get_connection(settings.db_path) as conn:
        issues = decimal_storage_issues(conn)
    if not issues:
        print(f"db-health=ok db_path={settings.db_path}")
        return
    print(f"db-health=warn db_path={settings.db_path}")
    for issue in issues:
        print(f"issue={issue}")
    raise SystemExit(2)


def cmd_select_leaders() -> None:
    _print_mapping(run_select_leaders.run())


def cmd_poll_trades() -> None:
    _print_mapping(run_poll_trades.run())


def cmd_generate_signals() -> None:
    _print_mapping(run_generate_signals.run())


def cmd_backfill_signals() -> None:
    _print_mapping(run_backfill_signals.run())


def cmd_simulate() -> None:
    _print_mapping(run_simulate.run())


def cmd_mark_to_market() -> None:
    _print_mapping(run_mark_to_market.run())


def cmd_daily_report() -> None:
    _print_mapping(run_daily_report.run())


def cmd_final_report() -> None:
    _print_mapping(run_final_report.run())


def cmd_run_loop() -> None:
    result = run_pipeline.run()
    _print_mapping(result)
    if not result['completed']:
        raise SystemExit(1)


def cmd_shadow_run() -> None:
    result = run_shadow.run()
    _print_mapping(result)
    if not result['completed']:
        raise SystemExit(1)


def cmd_gate_report() -> None:
    _print_mapping(run_gate_report.run())


def cmd_shadow_evidence() -> None:
    _print_mapping(run_shadow_evidence.run())


def cmd_prune_data() -> None:
    _print_mapping(run_prune_data.run())


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python -m app.main init")
        print("  python -m app.main db-health")
        print("  python -m app.main select-leaders")
        print("  python -m app.main poll-trades")
        print("  python -m app.main generate-signals")
        print("  python -m app.main backfill-signals")
        print("  python -m app.main simulate")
        print("  python -m app.main mark-to-market")
        print("  python -m app.main daily-report")
        print("  python -m app.main final-report")
        print("  python -m app.main run-loop")
        print("  python -m app.main shadow-run")
        print("  python -m app.main gate-report")
        print("  python -m app.main shadow-evidence")
        print("  python -m app.main prune-data")
        raise SystemExit(1)

    cmd = sys.argv[1]

    if cmd == "init":
        cmd_init()
    elif cmd == "db-health":
        cmd_db_health()
    elif cmd == "select-leaders":
        cmd_select_leaders()
    elif cmd == "poll-trades":
        cmd_poll_trades()
    elif cmd == "generate-signals":
        cmd_generate_signals()
    elif cmd == "backfill-signals":
        cmd_backfill_signals()
    elif cmd == "simulate":
        cmd_simulate()
    elif cmd == "mark-to-market":
        cmd_mark_to_market()
    elif cmd == "daily-report":
        cmd_daily_report()
    elif cmd == "final-report":
        cmd_final_report()
    elif cmd == "run-loop":
        cmd_run_loop()
    elif cmd == "shadow-run":
        cmd_shadow_run()
    elif cmd == "gate-report":
        cmd_gate_report()
    elif cmd == "shadow-evidence":
        cmd_shadow_evidence()
    elif cmd == "prune-data":
        cmd_prune_data()
    else:
        raise SystemExit(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
