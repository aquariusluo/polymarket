# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Polymarket copy-trading MVP. Observes profitable Polymarket accounts, detects trade activity, generates signals through configurable filters, and simulates copy-trades with PnL tracking. Default posture is observe-only — live trades require explicit `auto_follow` enablement and an audited execution path documented in AGENTS.md.

## Commands

```bash
# Run the full pipeline (single iteration)
python -m app.main run-loop

# Run individual pipeline steps
python -m app.main init               # Initialize SQLite database
python -m app.main select-leaders      # Fetch top-N leaderboard accounts
python -m app.main poll-trades         # Fetch recent trades for tracked leaders
python -m app.main generate-signals    # Filter trades through acceptance criteria
python -m app.main simulate            # Simulate copy-trades for accepted signals
python -m app.main mark-to-market      # Revalue open positions at current prices
python -m app.main daily-report        # Write daily performance report
python -m app.main final-report        # Write 60-day evaluation verdict
python -m app.main shadow-run          # Full pipeline + Scarf dashboard update

# Tests
pytest                                # Run all tests
pytest tests/test_filters.py          # Run a single test file
pytest -k "test_signal"              # Run tests matching a name pattern

# Lint
ruff check .
```

## Architecture

### Pipeline Flow

`select-leaders` → `poll-trades` → `generate-signals` → `simulate` → `mark-to-market` → `daily-report`

Each step is a job in `app/jobs/run_*.py` that returns a standardized dict with `steps` (list of {name, status, result/error}). `run_pipeline` chains all steps via `SchedulerService`; `run_shadow` wraps the pipeline with Scarf dashboard/report writes.

### Layer Structure

- **`app/clients/`** — HTTP clients for Polymarket API (leaderboard, trades, market data). All use `httpx`.
- **`app/domain/`** — Data models (`Leader`, `LeaderTrade`, `MarketInfo`, `SignalDecision`) and `TradeFilter` acceptance logic.
- **`app/services/`** — Business logic: signal generation, simulation, valuation, reporting, Scarf integration, scheduling, artifact output.
- **`app/jobs/`** — Thin wrappers that wire a service call into the pipeline step protocol. Each exports `run(settings, **kwargs) -> dict`.
- **`app/storage/`** — SQLite via `sqlite3` stdlib. `db.py` handles connection/schema init; `repositories.py` has one repository class per table. All repos take a `sqlite3.Connection` constructor arg.
- **`app/config.py`** — Frozen `Settings` dataclass. Values come from env vars with fallbacks from `.scarf/manifest.json` via `scarf_service.manifest_defaults()`.

### Database

SQLite at `data/app.db` (configurable via `DB_PATH`). Schema in `app/storage/schema.sql`. Tables: `leaders`, `leader_trades`, `markets`, `signals`, `sim_orders`, `positions`, `portfolio_snapshots`, `job_runs`.

### Trade Filter Criteria

Trades are rejected unless all pass: side is BUY, has condition_id, market found, market active and not closed, liquidity >= `min_market_liquidity`, time to expiry >= `min_time_to_expiry_hours`, asset_id matches market tokens. See `app/domain/filters.py`.

### Scarf Integration

`app/services/scarf_service.py` reads `.scarf/manifest.json` for configuration (execution mode, bankroll, risk limits) and writes dashboard widgets by title to `.scarf/dashboard.json`, plus report files under `.scarf/reports/`.

## Conventions

- Immutable `@dataclass(frozen=True)` for settings; plain dataclasses for domain models.
- Repository pattern: each table has its own class in `repositories.py`.
- `INSERT OR IGNORE` with UNIQUE constraints for deduplication.
- Job results are plain dicts, not typed objects — consumed by `_print_mapping()` in `main.py`.
- All env vars have sensible defaults — no `.env` file is required to run.
