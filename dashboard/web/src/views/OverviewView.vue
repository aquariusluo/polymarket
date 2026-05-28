<script setup lang="ts">
import api from '../api/client'
import { ref } from 'vue'
import { useRefresh } from '../stores/refresh'
import StatCard from '../components/StatCard.vue'
import StatusBadge from '../components/StatusBadge.vue'
import type { OverviewData } from '../types'

const data = ref<OverviewData | null>(null)
const { lastRefreshed, isLoading, isRefetching, error, refresh } = useRefresh(fetch)

async function fetch() {
  data.value = await api.getOverview()
}

const pnlColor = (v: number) => v >= 0 ? 'text-green-400' : 'text-red-400'
const fmt = (v: number) => `$${v.toFixed(2)}`
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-6">
      <div class="flex items-center gap-4">
        <h1 class="text-2xl font-bold text-white">Overview</h1>
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
    <div v-if="error && !data" class="bg-red-900/20 border border-red-800 text-red-400 p-4 rounded-lg mb-6 flex justify-between items-center">
      <span>Failed to load overview data. {{ error.message }}</span>
      <button @click="refresh" class="bg-red-800 text-white px-3 py-1 rounded text-xs hover:bg-red-700 transition">
        Retry
      </button>
    </div>

    <div v-if="isLoading" class="text-gray-400 animate-pulse py-8 text-center">
      <div class="inline-block animate-spin rounded-full h-4 w-4 border-b-2 border-purple-500 mr-2"></div>
      Loading dashboard overview...
    </div>

    <template v-else-if="data">
      <div class="grid grid-cols-4 gap-4 mb-6">
        <StatCard label="Total Equity" :value="fmt(data.total_equity)" />
        <StatCard label="Unrealized PnL" :value="fmt(data.total_unrealized_pnl)" :color="pnlColor(data.total_unrealized_pnl)" />
        <StatCard label="Realized PnL" :value="fmt(data.total_realized_pnl)" :color="pnlColor(data.total_realized_pnl)" />
        <StatCard label="Drawdown" :value="`${data.drawdown_pct.toFixed(1)}%`" color="text-yellow-400" />
      </div>

      <div class="grid grid-cols-4 gap-4 mb-6">
        <StatCard label="Open Positions" :value="String(data.open_position_count)" />
        <StatCard label="Accepted Signals" :value="String(data.accepted_signal_count)" color="text-green-400" />
        <StatCard label="Filled Orders" :value="String(data.filled_order_count)" color="text-blue-400" />
        <StatCard label="Tracked Leaders" :value="String(data.tracked_leader_count)" />
      </div>

      <div class="bg-gray-800 rounded-lg p-5">
        <h2 class="text-sm font-semibold text-gray-300 mb-3">Gate Status</h2>
        <div class="flex items-center gap-3 mb-3">
          <StatusBadge :status="data.gate_status" />
          <span class="text-sm text-gray-400">{{ data.gate_decision }}</span>
        </div>
        <div class="flex items-center gap-4 text-xs text-gray-500 mb-2">
          <span>Mode: <span class="text-gray-300">{{ data.execution_mode }}</span></span>
          <span>Pipeline: <span class="text-gray-300">{{ data.pipeline_status ?? 'idle' }}</span></span>
        </div>
        <div v-if="Object.keys(data.gate_thresholds).length" class="grid grid-cols-3 gap-2 mb-3 text-xs text-gray-500">
          <div>Fills needed: <span class="text-gray-300">{{ data.gate_thresholds.min_filled_orders_window }}</span></div>
          <div>Max ratio: <span class="text-gray-300">{{ data.gate_thresholds.max_accept_to_fill_ratio }}:1</span></div>
          <div>Max drawdown: <span class="text-gray-300">{{ data.gate_thresholds.max_drawdown_pct }}%</span></div>
        </div>
        <ul v-if="data.gate_notes.length" class="list-disc list-inside text-xs text-gray-400 space-y-0.5">
          <li v-for="(note, i) in data.gate_notes" :key="i">{{ note }}</li>
        </ul>
      </div>
    </template>
    <div v-else-if="!error" class="text-center py-12 text-gray-500 bg-gray-800 rounded-lg">
      No overview data available.
    </div>
  </div>
</template>
