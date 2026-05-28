<script setup lang="ts">
import api from '../api/client'
import { ref } from 'vue'
import { useRefresh } from '../stores/refresh'
import StatCard from '../components/StatCard.vue'
import StatusBadge from '../components/StatusBadge.vue'
import type { Signal, SignalFunnel } from '../types'

const signals = ref<Signal[]>([])
const funnel = ref<SignalFunnel | null>(null)
const loading = ref(true)
const { lastRefreshed } = useRefresh(fetch)

async function fetch() {
  const [s, f] = await Promise.all([api.getSignals(), api.getSignalFunnel()])
  signals.value = s
  funnel.value = f
  loading.value = false
}
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-2xl font-bold text-white">Signals</h1>
      <span v-if="lastRefreshed" class="text-xs text-gray-500">
        Updated {{ lastRefreshed.toLocaleTimeString() }}
      </span>
    </div>

    <div v-if="loading" class="text-gray-400">Loading...</div>

    <template v-else-if="funnel">
      <div class="grid grid-cols-5 gap-3 mb-6">
        <StatCard label="Total Trades" :value="String(funnel.total_trades)" />
        <StatCard label="Accepted" :value="String(funnel.accepted_signals)" color="text-green-400" />
        <StatCard label="Rejected" :value="String(funnel.rejected_signals)" color="text-red-400" />
        <StatCard label="Filled" :value="String(funnel.filled_orders)" color="text-blue-400" />
        <StatCard label="Pending" :value="String(funnel.pending_signals)" color="text-yellow-400" />
      </div>

      <table class="w-full text-sm">
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
    </template>
  </div>
</template>
