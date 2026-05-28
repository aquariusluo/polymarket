<script setup lang="ts">
import api from '../api/client'
import { ref, computed } from 'vue'
import { useRefresh } from '../stores/refresh'
import LineChart from '../components/LineChart.vue'
import type { Position, PortfolioSnapshot } from '../types'

const positions = ref<Position[]>([])
const snapshots = ref<PortfolioSnapshot[]>([])
const { lastRefreshed, isLoading, isRefetching, error, refresh } = useRefresh(fetch)

async function fetch() {
  const [p, s] = await Promise.all([api.getPortfolio(), api.getSnapshots()])
  positions.value = p
  snapshots.value = s
}

const chartLabels = computed(() =>
  snapshots.value.map((s) => new Date(s.captured_at).toLocaleDateString())
)

const chartDatasets = computed(() => [
  {
    label: 'Total Equity',
    data: snapshots.value.map((s) => s.total_equity),
    borderColor: '#a78bfa',
    backgroundColor: 'rgba(167, 139, 250, 0.1)',
  },
  {
    label: 'Cost Basis',
    data: snapshots.value.map((s) => s.total_cost_basis),
    borderColor: '#6b7280',
    backgroundColor: 'rgba(107, 114, 128, 0.05)',
  },
])
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-6">
      <div class="flex items-center gap-4">
        <h1 class="text-2xl font-bold text-white">Portfolio</h1>
        <span v-if="isRefetching" class="text-xs text-blue-400 animate-pulse">Refreshing...</span>
      </div>
      <div class="flex flex-col items-end">
        <span v-if="lastRefreshed" class="text-xs text-gray-500">
          Updated {{ lastRefreshed.toLocaleTimeString() }}
        </span>
        <button v-if="error" @click="refresh" class="text-xs text-red-400 underline hover:text-red-300">
          Retry
        </button>
      </div>
    </div>

    <!-- Error Alert -->
    <div v-if="error && !snapshots.length" class="bg-red-900/20 border border-red-800 text-red-400 p-4 rounded-lg mb-6 flex justify-between items-center">
      <div class="flex items-center gap-2">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clip-rule="evenodd" />
        </svg>
        <span>Failed to load portfolio data. {{ error.message }}</span>
      </div>
      <button @click="refresh" class="bg-red-800 text-white px-3 py-1 rounded text-xs hover:bg-red-700 transition">
        Retry
      </button>
    </div>

    <div v-if="snapshots.length" class="bg-gray-800 rounded-lg p-4 mb-6">
      <h2 class="text-sm font-semibold text-gray-300 mb-3">Equity Curve</h2>
      <LineChart :labels="chartLabels" :datasets="chartDatasets" />
    </div>
    <div v-else-if="isLoading" class="bg-gray-800 rounded-lg p-4 mb-6 text-center text-gray-500 text-sm h-64 flex flex-col justify-center items-center">
      <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-purple-500 mb-4"></div>
      Loading equity curve...
    </div>
    <div v-else-if="!error" class="bg-gray-800 rounded-lg p-4 mb-6 text-center text-gray-500 text-sm h-32 flex items-center justify-center">
      No historical data available for the equity curve.
    </div>

    <table v-if="positions.length" class="w-full text-sm">
      <thead>
        <tr class="text-left text-gray-400 border-b border-gray-700">
          <th class="pb-2">Market</th>
          <th class="pb-2">Side</th>
          <th class="pb-2">Shares</th>
          <th class="pb-2">Avg Cost</th>
          <th class="pb-2">Cost Basis</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="p in positions" :key="p.asset_id" class="border-b border-gray-800 text-gray-300">
          <td class="py-2">{{ p.market_slug }}</td>
          <td class="py-2">{{ p.side }}</td>
          <td class="py-2">{{ p.shares }}</td>
          <td class="py-2">{{ p.avg_cost }}</td>
          <td class="py-2">{{ p.cost_basis }}</td>
        </tr>
      </tbody>
    </table>
    <div v-else-if="!isLoading && !error" class="text-center py-12 text-gray-500">
      No open positions found.
    </div>
  </div>
</template>
