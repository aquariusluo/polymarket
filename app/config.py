from __future__ import annotations

import functools
import os
from dataclasses import dataclass, field
from pathlib import Path

from app.config_manifest import manifest_defaults


def _env(key: str, default: str) -> str:
    value = os.getenv(key)
    return value if value is not None else default


def _project_root(project_root: str | Path | None = None) -> Path:
    return Path(project_root) if project_root is not None else Path.cwd()


def _validated_db_path(raw_path: str, project_root: str | Path | None = None) -> str:
    if raw_path == ':memory:':
        if _env('APP_ENV', 'dev') != 'test':
            raise ValueError("DB_PATH=':memory:' is only supported when APP_ENV=test")
        return raw_path
    root = _project_root(project_root).resolve()
    path = Path(raw_path)
    resolved = (root / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f'DB_PATH must stay within project root: {root}') from exc
    return str(resolved)


@dataclass(frozen=True)
class ScarfConfig:
    execution_mode: str = 'manual_confirm'
    bankroll_usd: float = 0.0
    max_daily_orders: int = 10
    evaluation_days: int = 60
    top_accounts_override: tuple[str, ...] = field(default_factory=tuple)
    excluded_wallets: tuple[str, ...] = field(default_factory=tuple)
    operator_notes: str = ''
    leader_selection_mode: str = 'live_top5'
    leaderboard_source: str = 'Polymarket profit leaderboard'
    evaluation_start_date: str = ''


@dataclass(frozen=True)
class Settings:
    app_env: str
    db_path: str
    leaderboard_category: str
    leaderboard_time: str
    leaderboard_sort: str
    top_n: int
    poll_interval_seconds: int
    trade_fetch_limit: int
    min_time_to_expiry_hours: int
    min_market_liquidity: float
    signal_cooldown_minutes: int
    data_source: str = 'http'
    signal_batch_limit: int = 500
    max_trade_age_minutes: int = 60
    max_trade_age_at_fill_minutes: int | None = None
    max_signal_age_minutes: int = 15
    fixed_trade_usdc: float = 100.0
    per_market_cap_usdc: float = 300.0
    max_slippage_pct: float = 2.0
    market_cache_ttl_seconds: int = 300
    run_loop_max_iterations: int = 1
    run_loop_sleep_seconds: int = 0
    retention_days_leader_trades: int = 30
    retention_days_signals: int = 30
    retention_days_job_runs: int = 30
    retention_days_portfolio_snapshots: int = 60
    scarf_execution_mode: str = 'manual_confirm'
    scarf_bankroll_usd: float = 0.0
    max_daily_orders: int = 10
    scarf_evaluation_days: int = 60
    scarf_top_accounts_override: tuple[str, ...] = field(default_factory=tuple)
    scarf_excluded_wallets: tuple[str, ...] = field(default_factory=tuple)
    scarf_operator_notes: str = ''
    scarf_leader_selection_mode: str = 'live_top5'
    scarf_leaderboard_source: str = 'Polymarket profit leaderboard'
    scarf_evaluation_start_date: str = ''

    @property
    def effective_max_trade_age_at_fill_minutes(self) -> int:
        if self.max_trade_age_at_fill_minutes is None:
            return int(self.max_trade_age_minutes)
        return int(self.max_trade_age_at_fill_minutes)

    @property
    def scarf(self) -> ScarfConfig:
        return ScarfConfig(
            execution_mode=self.scarf_execution_mode,
            bankroll_usd=self.scarf_bankroll_usd,
            max_daily_orders=self.max_daily_orders,
            evaluation_days=self.scarf_evaluation_days,
            top_accounts_override=tuple(self.scarf_top_accounts_override),
            excluded_wallets=tuple(self.scarf_excluded_wallets),
            operator_notes=self.scarf_operator_notes,
            leader_selection_mode=self.scarf_leader_selection_mode,
            leaderboard_source=self.scarf_leaderboard_source,
            evaluation_start_date=self.scarf_evaluation_start_date,
        )


@functools.lru_cache(maxsize=1)
def get_settings(project_root=None) -> Settings:
    defaults = manifest_defaults(project_root)
    top_accounts_override = list(defaults.get('top_accounts_override') or [])
    leader_selection_mode = str(defaults.get('leader_selection_mode', 'live_top5'))
    top_n_default = len(top_accounts_override) if leader_selection_mode == 'fixed_override' and top_accounts_override else 5
    fixed_trade_default = float(defaults.get('max_copy_usd_per_order', 100))
    max_slippage_default = float(defaults.get('slippage_bps', 200)) / 100.0
    env_slippage_bps = os.getenv('MAX_SLIPPAGE_BPS')
    if env_slippage_bps is not None:
        max_slippage_pct = float(env_slippage_bps) / 100.0
    else:
        max_slippage_pct = float(_env('MAX_SLIPPAGE_PCT', str(max_slippage_default)))
    scarf = ScarfConfig(
        execution_mode=str(defaults.get('execution_mode', 'manual_confirm')),
        bankroll_usd=float(defaults.get('bankroll_usd', 0.0)),
        max_daily_orders=int(defaults.get('max_daily_orders', 10)),
        evaluation_days=int(defaults.get('evaluation_days', 60)),
        top_accounts_override=tuple(top_accounts_override),
        excluded_wallets=tuple(defaults.get('excluded_wallets') or []),
        operator_notes=str(defaults.get('operator_notes', '')),
        leader_selection_mode=leader_selection_mode,
        leaderboard_source=str(defaults.get('leaderboard_source', 'Polymarket profit leaderboard')),
        evaluation_start_date=str(defaults.get('evaluation_start_date', '')),
    )
    return Settings(
        app_env=_env('APP_ENV', 'dev'),
        db_path=_validated_db_path(_env('DB_PATH', './data/app.db'), project_root),
        data_source=_env('DATA_SOURCE', _env('POLYMARKET_DATA_SOURCE', 'http')),
        leaderboard_category=_env('LEADERBOARD_CATEGORY', 'overall'),
        leaderboard_time=_env('LEADERBOARD_TIME', '30d'),
        leaderboard_sort=_env('LEADERBOARD_SORT', 'profit'),
        top_n=int(_env('TOP_N', str(top_n_default))),
        poll_interval_seconds=int(_env('POLL_INTERVAL_SECONDS', '10')),
        trade_fetch_limit=int(_env('TRADE_FETCH_LIMIT', '50')),
        min_time_to_expiry_hours=int(_env('MIN_TIME_TO_EXPIRY_HOURS', '24')),
        min_market_liquidity=float(_env('MIN_MARKET_LIQUIDITY', '10000')),
        signal_cooldown_minutes=int(_env('SIGNAL_COOLDOWN_MINUTES', '5')),
        signal_batch_limit=int(_env('SIGNAL_BATCH_LIMIT', '500')),
        max_trade_age_minutes=int(_env('MAX_TRADE_AGE_MINUTES', '60')),
        max_trade_age_at_fill_minutes=int(_env('MAX_TRADE_AGE_AT_FILL_MINUTES', _env('MAX_TRADE_AGE_MINUTES', '60'))),
        max_signal_age_minutes=int(_env('MAX_SIGNAL_AGE_MINUTES', '15')),
        fixed_trade_usdc=float(_env('FIXED_TRADE_USDC', str(fixed_trade_default))),
        per_market_cap_usdc=float(_env('PER_MARKET_CAP_USDC', '300')),
        max_slippage_pct=max_slippage_pct,
        market_cache_ttl_seconds=int(_env('MARKET_CACHE_TTL_SECONDS', '300')),
        run_loop_max_iterations=int(_env('RUN_LOOP_MAX_ITERATIONS', '1')),
        run_loop_sleep_seconds=int(_env('RUN_LOOP_SLEEP_SECONDS', '0')),
        retention_days_leader_trades=int(_env('RETENTION_DAYS_LEADER_TRADES', '30')),
        retention_days_signals=int(_env('RETENTION_DAYS_SIGNALS', '30')),
        retention_days_job_runs=int(_env('RETENTION_DAYS_JOB_RUNS', '30')),
        retention_days_portfolio_snapshots=int(_env('RETENTION_DAYS_PORTFOLIO_SNAPSHOTS', '60')),
        scarf_execution_mode=scarf.execution_mode,
        scarf_bankroll_usd=scarf.bankroll_usd,
        max_daily_orders=scarf.max_daily_orders,
        scarf_evaluation_days=scarf.evaluation_days,
        scarf_top_accounts_override=scarf.top_accounts_override,
        scarf_excluded_wallets=scarf.excluded_wallets,
        scarf_operator_notes=scarf.operator_notes,
        scarf_leader_selection_mode=scarf.leader_selection_mode,
        scarf_leaderboard_source=scarf.leaderboard_source,
        scarf_evaluation_start_date=scarf.evaluation_start_date,
    )
