const BASE = ''

async function request<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json() as Promise<T>
}

export default {
  getOverview: () => request<import('../types').OverviewData>('/api/overview'),
  getPortfolio: () => request<import('../types').Position[]>('/api/portfolio'),
  getSnapshots: (limit = 200) => request<import('../types').PortfolioSnapshot[]>(`/api/portfolio/snapshots?limit=${limit}`),
  getSignals: (limit = 50, offset = 0) => request<import('../types').Signal[]>(`/api/signals?limit=${limit}&offset=${offset}`),
  getSignalFunnel: () => request<import('../types').SignalFunnel>('/api/signals/funnel'),
  getLeaders: () => request<import('../types').Leader[]>('/api/leaders'),
  getLeaderTrades: (wallet: string, limit = 20) => request<import('../types').LeaderTrade[]>(`/api/leaders/${wallet}/trades?limit=${limit}`),
  getJobRuns: (limit = 30) => request<import('../types').JobRun[]>(`/api/pipeline/runs?limit=${limit}`),
  getMonitorLog: (limit = 50) => request<import('../types').MonitorEvent[]>(`/api/pipeline/monitor?limit=${limit}`),
}
