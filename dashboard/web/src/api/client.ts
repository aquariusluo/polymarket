const BASE = ''
const MAX_RETRIES = 2

async function request<T>(path: string): Promise<T> {
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    const res = await fetch(`${BASE}${path}`)
    if (res.ok) return res.json() as Promise<T>
    if (res.status >= 500 && attempt < MAX_RETRIES) {
      await new Promise((r) => setTimeout(r, 300 * (attempt + 1)))
      continue
    }
    throw new Error(`API error: ${res.status}`)
  }
  throw new Error('API unavailable after retries')
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
