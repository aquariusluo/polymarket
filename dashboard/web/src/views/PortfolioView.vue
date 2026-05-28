<script setup lang="ts">
import api from '../api/client'
import { ref, computed } from 'vue'
import { useRefresh } from '../stores/refresh'
import LineChart from '../components/LineChart.vue'
import type { Position, PortfolioSnapshot } from '../types'

const positions = ref<Position[]>([])
const snapshots = ref<PortfolioSnapshot[]>([])
const loading = ref(true)
const { lastRefreshed } = useRefresh(fetch)

async function fetch() {
  const [p, s] = await Promise.all([api.getPortfolio(), api.getSnapshots()])
  positions.value = p
  snapshots.value = s
  loading.value = false
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
      <h1 class="text-2xl font-bold text-white">Portfolio</h1>
      <span v-if="lastRefreshed" class="text-xs text-gray-500">
        Updated {{ lastRefreshed.toLocaleTimeString() }}
      </span>
    </div>

    <div v-if="loading" class="text-gray-400">Loading...</div>

    <template v-else>
      <div v-if="snapshots.length" class="bg-gray-800 rounded-lg p-4 mb-6">
        <h2 class="text-sm font-semibold text-gray-300 mb-3">Equity Curve</h2>
        <LineChart :labels="chartLabels" :datasets="chartDatasets" />
      </div>

      <table class="w-full text-sm">
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
    </template>
  </div>
</template>
