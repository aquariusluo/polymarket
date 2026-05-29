# Polymarket Leader Follower

Copy-trading MVP for Polymarket prediction markets. Observes profitable accounts, detects trade activity, generates signals through configurable filters, and simulates copy-trades with PnL tracking. Default posture is **observe-only** — live trades require explicit auto-follow enablement and an audited execution path.

## Architecture

```
select-leaders → poll-trades → generate-signals → simulate → mark-to-market → daily-report
```

Each step is a job in `app/jobs/run_*.py` that returns a standardized dict. `run_pipeline` chains all steps; `run_shadow` wraps the pipeline with dashboard and report writes.

### Layers

| Layer | Purpose |
|-------|---------|
| `app/clients/` | HTTP clients for Polymarket API (leaderboard, trades, market data) via `httpx` |
| `app/domain/` | Data models (`Leader`, `LeaderTrade`, `MarketInfo`, `SignalDecision`) and `TradeFilter` acceptance logic |
| `app/services/` | Business logic: signal generation, simulation, valuation, reporting, scheduling |
| `app/jobs/` | Thin wrappers wiring service calls into the pipeline step protocol |
| `app/storage/` | SQLite via stdlib `sqlite3` (WAL mode). Schema in `storage/schema.sql` |
| `dashboard/` | Vue 3 + FastAPI monitoring dashboard |

### Database

SQLite at `data/app.db` (configurable via `DB_PATH`). Tables: `leaders`, `leader_trades`, `markets`, `signals`, `sim_orders`, `positions`, `portfolio_snapshots`, `job_runs`.

## Monitoring Dashboard

Real-time dashboard for pipeline status, portfolio performance, and gate evaluation.

### Stack

- **Backend**: FastAPI + uvicorn (read-only GET endpoints)
- **Frontend**: Vue 3 + TypeScript + Vite + Tailwind CSS v4

### Pages

| Page | What it shows |
|------|---------------|
| **Overview** | Equity, PnL, drawdown, gate status with thresholds, pipeline status |
| **Portfolio** | Current positions with cost basis and unrealized PnL |
| **Signals** | Signal funnel: detected → accepted/rejected → filled/rejected orders |
| **Leaders** | Tracked leader rankings with trade counts and PnL |
| **Pipeline** | Recent job runs with timing and row counts |

### Starting the dashboard

```bash
# Backend (port 8000)
cd dashboard && python api/main.py

# Frontend (port 5173, dev mode)
cd dashboard/web && npm run dev
```

## Auto-Follow Gate

A safety mechanism that evaluates whether the system is ready to promote from observe-only to auto-trade mode. Uses a **72-hour rolling window** with these checks:

| Check | Threshold | Rationale |
|-------|-----------|-----------|
| Min filled orders | 10 | Single lucky trade shouldn't open the gate |
| Accept-to-fill ratio | 4:1 | 25% fill rate is still demanding |
| Slippage reject ratio | 60% | Reject if slippage dominates rejections |
| Max drawdown | 10% | Hard-lock if simulated losses exceed 10% |
| Min unique markets | 3 | Fills must be spread across different markets |
| Realized PnL | Non-negative | System must not be losing money |

The gate produces a report at `.scarf/reports/auto-follow-gate.{md,json}` with structured diagnostic notes. Status is either `pass` (auto-follow candidate) or `hold` (manual confirm only).

## Commands

```bash
# Full pipeline (single iteration)
python -m app.main run-loop

# Individual pipeline steps
python -m app.main init               # Initialize SQLite database
python -m app.main select-leaders    # Fetch top-N leaderboard accounts
python -m app.main poll-trades       # Fetch recent trades for tracked leaders
python -m app.main generate-signals  # Filter trades through acceptance criteria
python -m app.main simulate          # Simulate copy-trades for accepted signals
python -m app.main mark-to-market     # Revalue open positions at current prices
python -m app.main daily-report      # Write daily performance report
python -m app.main final-report      # Write 60-day evaluation verdict
python -m app.main gate-report       # Generate auto-follow gate decision

# Shadow run (full pipeline + dashboard update)
python -m app.main shadow-run

# Tests & lint
pytest
ruff check .
```

## Trade Filter Criteria

Trades are rejected unless all pass: side is BUY, has condition_id, market found, market active and not closed, liquidity >= min threshold, time to expiry >= min hours, asset_id matches market tokens. See `app/domain/filters.py`.

## Data Sources

### Polymarket API (default)

Direct HTTP calls to Polymarket REST endpoints for leaderboard and trade data.

### Polymarket CLI (optional)

Use the local read-only CLI for leaderboard and trade discovery:

```bash
DATA_SOURCE=polymarket_cli python -m app.main select-leaders
DATA_SOURCE=polymarket_cli python -m app.main poll-trades
```

Run the lightweight 5-minute monitor once:

```bash
scripts/run_polymarket_cli_monitor.py
```

Run one complete shadow/paper pipeline pass:

```bash
scripts/run_polymarket_cli_shadow.sh
```

Install the macOS LaunchAgent to run the 5-minute monitor automatically:

```bash
scripts/install_polymarket_cli_shadow_launchd.sh
```

Install optional macOS log rotation (newsyslog) to cap monitor logs:

```bash
scripts/install_polymarket_cli_logrotate_macos.sh
```

Run one-shot healthcheck (exit code: `0=PASS`, `1=PASS with warnings`, `2=FAIL`):

```bash
scripts/healthcheck_polymarket_shadow.sh
```

Machine-readable JSON output:

```bash
scripts/healthcheck_polymarket_shadow.sh --json
```

Stop and remove it:

```bash
scripts/uninstall_polymarket_cli_shadow_launchd.sh
```

## Configuration

Environment variables with fallbacks from `.scarf/manifest.json`:

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PATH` | `data/app.db` | SQLite database path |
| `DATA_SOURCE` | `polymarket_api` | `polymarket_api` or `polymarket_cli` |
| `TRADE_FETCH_LIMIT` | 20 | Max trades per leader per poll |
| `SIGNAL_BATCH_LIMIT` | 50 | Max signals processed per run |

## DB Precision Migration

If your local DB was created before the Decimal/TEXT storage change:

```bash
python scripts/migrate_sqlite_decimal_text.py --db-path data/app.db
```

Verify without modifying:

```bash
python scripts/migrate_sqlite_decimal_text.py --db-path data/app.db --verify-only
```

Check runtime DB health:

```bash
python -m app.main db-health
```

Enable strict startup enforcement (fail fast on old schema):

```bash
DB_DECIMAL_SCHEMA_STRICT=1 python -m app.main run-loop
```

## For Agents

See `AGENTS.md` for the full operating contract, file layout, and update rules. See `CLAUDE.md` for Claude Code-specific guidance.
