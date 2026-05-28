export interface OverviewData {
  execution_mode: string
  bankroll_usd: number
  total_equity: number
  total_unrealized_pnl: number
  total_realized_pnl: number
  drawdown_pct: number
  open_position_count: number
  accepted_signal_count: number
  filled_order_count: number
  rejected_order_count: number
  tracked_leader_count: number
  gate_status: string
  gate_decision: string
  gate_notes: string[]
  last_pipeline_at: string | null
  pipeline_status: string | null
}

export interface Position {
  condition_id: string
  asset_id: string
  market_slug: string
  side: string
  shares: string
  avg_cost: string
  cost_basis: string
  updated_at: string
}

export interface PortfolioSnapshot {
  captured_at: string
  total_equity: number
  total_cost_basis: number
  total_market_value: number
  total_unrealized_pnl: number
  total_realized_pnl: number
  drawdown_pct: number
}

export interface Signal {
  id: number
  wallet: string
  leader_name: string | null
  condition_id: string
  market_slug: string
  side: string
  leader_price: string
  decision: string
  reason: string
  detected_at: string
  order_status: string | null
  order_reason: string | null
}

export interface SignalFunnel {
  total_trades: number
  accepted_signals: number
  rejected_signals: number
  filled_orders: number
  rejected_orders: number
  pending_signals: number
}

export interface Leader {
  rank: number
  wallet: string
  name: string | null
  pseudonym: string | null
  pnl_snapshot: number
  volume_snapshot: number
  selected_at: string
  trade_count: number
  last_trade_at: string | null
}

export interface LeaderTrade {
  id: number
  transaction_hash: string
  condition_id: string
  asset_id: string
  side: string
  size: string
  price: string
  timestamp: string
  market_title: string
  market_slug: string
  ingested_at: string
}

export interface JobRun {
  id: number
  job_name: string
  started_at: string
  finished_at: string
  duration: number | null
  status: string
  inserted_count: number
  skipped_count: number
  error_message: string | null
}

export interface MonitorEvent {
  timestamp: string
  event: string
  step?: string
  returncode?: number
  stdout?: string
  stderr?: string
  [key: string]: unknown
}
