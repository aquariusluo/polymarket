<script setup lang="ts">
import api from '../api/client'
import { ref } from 'vue'
import { useRefresh } from '../stores/refresh'
import StatusBadge from '../components/StatusBadge.vue'
import type { Signal, SignalFunnel } from '../types'

const signals = ref<Signal[]>([])
const funnel = ref<SignalFunnel | null>(null)
const { lastRefreshed, isLoading, isRefetching, error, refresh } = useRefresh(fetch)

async function fetch() {
  const [s, f] = await Promise.all([api.getSignals(), api.getSignalFunnel()])
  signals.value = s
  funnel.value = f
}
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-6">
      <div class="flex items-center gap-4">
        <h1 class="text-2xl font-bold text-white">Signals</h1>
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
    <div v-if="error && !funnel" class="bg-red-900/20 border border-red-800 text-red-400 p-4 rounded-lg mb-6 flex justify-between items-center">
      <div class="flex items-center gap-2">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clip-rule="evenodd" />
        </svg>
        <span>Failed to load signals. {{ error.message }}</span>
      </div>
      <button @click="refresh" class="bg-red-800 text-white px-3 py-1 rounded text-xs hover:bg-red-700 transition">
        Retry
      </button>
    </div>

    <template v-if="funnel">
      <div class="grid grid-cols-5 gap-3 mb-6">
        <div class="bg-gray-800 rounded-lg p-4 text-center">
          <div class="text-xs text-gray-400 mb-1">Total Trades</div>
          <div class="text-lg font-bold text-white">{{ funnel.total_trades }}</div>
        </div>
        <div class="bg-gray-800 rounded-lg p-4 text-center">
          <div class="text-xs text-gray-400 mb-1">Accepted</div>
          <div class="text-lg font-bold text-green-400">{{ funnel.accepted_signals }}</div>
        </div>
        <div class="bg-gray-800 rounded-lg p-4 text-center">
          <div class="text-xs text-gray-400 mb-1">Rejected</div>
          <div class="text-lg font-bold text-red-400">{{ funnel.rejected_signals }}</div>
        </div>
        <div class="bg-gray-800 rounded-lg p-4 text-center">
          <div class="text-xs text-gray-400 mb-1">Filled</div>
          <div class="text-lg font-bold text-blue-400">{{ funnel.filled_orders }}</div>
        </div>
        <div class="bg-gray-800 rounded-lg p-4 text-center">
          <div class="text-xs text-gray-400 mb-1">Pending</div>
          <div class="text-lg font-bold text-yellow-400">{{ funnel.pending_signals }}</div>
        </div>
      </div>
    </template>
    <div v-else-if="isLoading" class="grid grid-cols-5 gap-3 mb-6">
      <div v-for="i in 5" :key="i" class="bg-gray-800 rounded-lg p-4 text-center h-16 animate-pulse">
        <div class="h-3 w-16 bg-gray-700 rounded mx-auto mb-2"></div>
        <div class="h-5 w-10 bg-gray-700 rounded mx-auto"></div>
      </div>
    </div>
    <div v-else-if="!error" class="bg-gray-800 rounded-lg p-8 text-center text-gray-500 mb-6">
      No funnel data available.
    </div>

    <table v-if="signals.length" class="w-full text-sm">
      <thead>
        <tr class="text-left text-gray-400 border-b border-gray-700">
          <th class="pb-2">Leader</th>
          <th class="pb-2">Market</th>
          <th class="pb-2">Side</th>
          <th class="pb-2">Decision</th>
          <th class="pb-2">Order Status</th>
          <th class="pb-2">Detected</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="s in signals" :key="s.id" class="border-b border-gray-800 text-gray-300">
          <td class="py-2">{{ s.leader_name || s.wallet.slice(0, 8) }}</td>
          <td class="py-2">{{ s.market_slug }}</td>
          <td class="py-2">{{ s.side }}</td>
          <td class="py-2"><StatusBadge :status="s.decision" /></td>
          <td class="py-2">
            <StatusBadge v-if="s.order_status" :status="s.order_status" />
            <span v-else class="text-gray-500">—</span>
          </td>
          <td class="py-2 text-gray-500">{{ new Date(s.detected_at).toLocaleString() }}</td>
        </tr>
      </tbody>
    </table>
    <div v-else-if="!isLoading && !error" class="py-12 text-center text-gray-500">
      No signals detected yet.
    </div>
  </div>
</template>
