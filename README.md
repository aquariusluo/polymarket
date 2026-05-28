# Polymarket Leader Follower

This Scarf project tracks the top 5 profitable Polymarket accounts, captures new order activity, and helps you evaluate whether mirroring those trades is worth continuing after a 60-day run.

## In Scarf

1. Open the project in Scarf from `/Users/aquariusluo/Projects/polymarket`.
2. Open **Configuration** and fill in bankroll, execution mode, and risk limits.
3. Review the dashboard sections for watchlist status, latest activity, and rolling performance.

## Cron jobs

This project includes optional draft cron definitions in `cron/jobs.json`:

- a 5-minute monitor job for leader/order detection
- a daily review job for performance tracking
- a daily auto-follow gate report job that writes `.scarf/reports/auto-follow-gate.{md,json}`

These are not registered automatically for the local project yet.

## For agents

See `AGENTS.md` for the full operating contract, file layout, and update rules.

## DB precision migration

If your local DB was created before the Decimal/TEXT storage change, migrate it once:

```bash
.venv/bin/python scripts/migrate_sqlite_decimal_text.py --db-path data/app.db
```

Check current DB compatibility without modifying anything:

```bash
.venv/bin/python scripts/migrate_sqlite_decimal_text.py --db-path data/app.db --verify-only
```

Check runtime DB health from the app entrypoint:

```bash
.venv/bin/python -m app.main db-health
```

Enable strict startup enforcement (fail fast on old schema):

```bash
DB_DECIMAL_SCHEMA_STRICT=1 .venv/bin/python -m app.main run-loop
```

Generate the current auto-follow gate decision report:

```bash
.venv/bin/python -m app.main gate-report
```

## Polymarket CLI data source

The monitor can use the local read-only Polymarket CLI for leaderboard and trade discovery:

```bash
DATA_SOURCE=polymarket_cli .venv/bin/python -m app.main select-leaders
DATA_SOURCE=polymarket_cli .venv/bin/python -m app.main poll-trades
```

This path uses `polymarket data leaderboard`, `polymarket data trades`, and `polymarket clob market`.
It does not call wallet setup, approvals, or order-placement commands.

Run the lightweight 5-minute monitor path once with the CLI source:

```bash
scripts/run_polymarket_cli_monitor.py
```

Run one complete shadow/paper pipeline pass with the CLI source:

```bash
scripts/run_polymarket_cli_shadow.sh
```

Install the local macOS LaunchAgent to run the lightweight monitor every 5 minutes:

```bash
scripts/install_polymarket_cli_shadow_launchd.sh
```

Stop and remove it:

```bash
scripts/uninstall_polymarket_cli_shadow_launchd.sh
```

LaunchAgent stdout/stderr are written to `tmp/polymarket-cli-shadow.out.log` and
`tmp/polymarket-cli-shadow.err.log`. Per-step monitor results are appended to
`tmp/polymarket-cli-monitor.jsonl`.

The LaunchAgent defaults to `TRADE_FETCH_LIMIT=5` per leader per pass so the
5-minute monitor stays lightweight. It also defaults to `SIGNAL_BATCH_LIMIT=10`
so historical signal backfills cannot monopolize the monitor loop. Override
these only for one-off backfills.
