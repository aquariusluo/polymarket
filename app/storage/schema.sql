PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS leaders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rank INTEGER NOT NULL,
    wallet TEXT NOT NULL,
    name TEXT,
    pseudonym TEXT,
    pnl_snapshot REAL,
    volume_snapshot REAL,
    selection_run_id TEXT NOT NULL,
    selected_at TEXT NOT NULL,
    raw_json TEXT,
    UNIQUE(selection_run_id, wallet)
);

CREATE TABLE IF NOT EXISTS leader_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet TEXT NOT NULL,
    leader_name TEXT,
    transaction_hash TEXT NOT NULL,
    condition_id TEXT,
    asset_id TEXT NOT NULL,
    side TEXT,
    size TEXT,
    price TEXT,
    timestamp TEXT NOT NULL,
    market_title TEXT,
    market_slug TEXT,
    raw_json TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    UNIQUE(wallet, transaction_hash, asset_id)
);

CREATE TABLE IF NOT EXISTS markets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT NOT NULL UNIQUE,
    title TEXT,
    slug TEXT,
    end_time TEXT,
    liquidity TEXT,
    active INTEGER NOT NULL DEFAULT 0,
    closed INTEGER NOT NULL DEFAULT 0,
    yes_token_id TEXT,
    no_token_id TEXT,
    yes_outcome TEXT,
    no_outcome TEXT,
    raw_json TEXT NOT NULL,
    refreshed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    leader_trade_id INTEGER NOT NULL UNIQUE,
    wallet TEXT NOT NULL,
    leader_name TEXT,
    condition_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    market_slug TEXT,
    side TEXT,
    leader_price TEXT,
    decision TEXT NOT NULL,
    reason TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    raw_json TEXT,
    FOREIGN KEY (leader_trade_id) REFERENCES leader_trades(id)
);

CREATE TABLE IF NOT EXISTS sim_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER NOT NULL UNIQUE,
    condition_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    market_slug TEXT,
    side TEXT,
    requested_notional TEXT NOT NULL,
    filled_notional TEXT,
    filled_shares TEXT,
    fill_price TEXT,
    leader_price TEXT,
    slippage_pct TEXT,
    status TEXT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (signal_id) REFERENCES signals(id)
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    market_slug TEXT,
    side TEXT,
    shares TEXT NOT NULL,
    avg_cost TEXT NOT NULL,
    cost_basis TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(condition_id, asset_id)
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at TEXT NOT NULL,
    total_cost_basis TEXT NOT NULL,
    total_market_value TEXT NOT NULL,
    total_unrealized_pnl TEXT NOT NULL,
    total_realized_pnl TEXT NOT NULL,
    total_equity TEXT NOT NULL,
    drawdown_pct TEXT NOT NULL,
    raw_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    inserted_count INTEGER DEFAULT 0,
    skipped_count INTEGER DEFAULT 0,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_signals_decision ON signals(decision);
CREATE INDEX IF NOT EXISTS idx_signals_detected_at ON signals(detected_at);
CREATE INDEX IF NOT EXISTS idx_sim_orders_status ON sim_orders(status);
CREATE INDEX IF NOT EXISTS idx_sim_orders_signal_id ON sim_orders(signal_id);
CREATE INDEX IF NOT EXISTS idx_leader_trades_wallet ON leader_trades(wallet);
CREATE INDEX IF NOT EXISTS idx_leader_trades_ingested_at ON leader_trades(ingested_at);
CREATE INDEX IF NOT EXISTS idx_positions_condition_id ON positions(condition_id);
CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_captured_at ON portfolio_snapshots(captured_at);
