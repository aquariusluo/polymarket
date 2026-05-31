<script setup lang="ts">
import api from '../api/client'
import { computed, ref, watch } from 'vue'
import { useRefresh } from '../stores/refresh'
import StatusBadge from '../components/StatusBadge.vue'
import type { Signal, SignalFunnel } from '../types'

const signals = ref<Signal[]>([])
const funnel = ref<SignalFunnel | null>(null)
const expandedSignalId = ref<number | null>(null)
const signalQuery = ref('')
const { lastRefreshed, isLoading, isRefetching, error, refresh } = useRefresh(fetch)

function shortWallet(wallet: string) {
  return `${wallet.slice(0, 6)}...${wallet.slice(-4)}`
}

function displayLeader(signal: Signal) {
  return signal.leader_name || shortWallet(signal.wallet)
}

function toggleSignal(signalId: number) {
  expandedSignalId.value = expandedSignalId.value === signalId ? null : signalId
}

const filteredSignals = computed(() => {
  const q = signalQuery.value.trim().toLowerCase()
  if (!q) return signals.value
  return signals.value.filter((s) => {
    const leader = (s.leader_name || '').toLowerCase()
    const wallet = s.wallet.toLowerCase()
    const market = (s.market_slug || '').toLowerCase()
    return leader.includes(q) || wallet.includes(q) || market.includes(q)
  })
})

watch(filteredSignals, (items) => {
  if (expandedSignalId.value && !items.some((s) => s.id === expandedSignalId.value)) {
    expandedSignalId.value = null
  }
})

async function fetch() {
  const [s, f] = await Promise.all([api.getSignals(), api.getSignalFunnel()])
  signals.value = s
  funnel.value = f
}
</script>

<template>
  <div class="min-w-0">
    <div class="sticky top-[var(--mobile-nav-offset,6.5rem)] z-20 mb-3 rounded-lg border border-gray-800/80 bg-gray-950/90 px-3 py-2 backdrop-blur sm:hidden">
      <div class="flex items-center justify-between">
        <h1 class="text-lg font-bold text-white">Signals</h1>
        <button
          @click="refresh"
          class="min-h-11 rounded-md border border-gray-700 px-3 py-2 text-xs text-gray-300 hover:bg-gray-800"
        >
          Refresh
        </button>
      </div>
      <p v-if="lastRefreshed" class="mt-1 text-[11px] text-gray-400">
        Updated {{ lastRefreshed.toLocaleTimeString() }}
      </p>
      <input
        v-model="signalQuery"
        type="text"
        aria-label="Search signals by leader, wallet, or market"
        placeholder="Search leader, wallet, market..."
        class="mt-2 min-h-11 w-full rounded-md border border-gray-700 bg-gray-900 px-3 py-2 text-xs text-gray-200 placeholder:text-gray-400 focus:border-blue-500 focus:outline-none"
      />
    </div>

    <div class="mb-5 hidden flex-col gap-2 sm:mb-6 sm:flex sm:flex-row sm:items-center sm:justify-between">
      <div class="flex items-center gap-3">
        <h1 class="text-xl font-bold text-white sm:text-2xl">Signals</h1>
        <span v-if="isRefetching" class="text-xs text-blue-400 animate-pulse">Refreshing...</span>
      </div>
      <div class="flex flex-col sm:items-end">
        <input
          v-model="signalQuery"
          type="text"
          aria-label="Search signals by leader, wallet, or market"
          placeholder="Search leader, wallet, market..."
          class="hidden w-72 rounded-md border border-gray-700 bg-gray-900 min-h-11 px-2.5 py-1.5 text-xs text-gray-200 placeholder:text-gray-400 focus:border-blue-500 focus:outline-none sm:block"
        />
        <span v-if="lastRefreshed" class="text-xs text-gray-400">
          Updated {{ lastRefreshed.toLocaleTimeString() }}
        </span>
        <button v-if="error" @click="refresh" class="min-h-11 px-3 py-2 text-xs text-red-400 underline hover:text-red-300">
          Retry
        </button>
      </div>
    </div>

    <!-- Error Alert -->
    <div v-if="error && !funnel" role="alert" class="mb-6 flex flex-col gap-3 rounded-lg border border-red-800 bg-red-900/20 p-4 text-red-400 sm:flex-row sm:items-center sm:justify-between">
      <div class="flex items-center gap-2">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clip-rule="evenodd" />
        </svg>
        <span class="break-words">Failed to load signals. {{ error.message }}</span>
      </div>
      <button @click="refresh" class="min-h-11 rounded bg-red-800 px-3 py-2 text-xs text-white transition hover:bg-red-700">
        Retry
      </button>
    </div>

    <template v-if="funnel">
      <div class="mb-5 grid grid-cols-2 gap-3 sm:mb-6 sm:grid-cols-5">
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
    <div v-else-if="isLoading" class="mb-5 grid grid-cols-2 gap-3 sm:mb-6 sm:grid-cols-5">
      <div v-for="i in 5" :key="i" class="bg-gray-800 rounded-lg p-4 text-center h-16 animate-pulse">
        <div class="h-3 w-16 bg-gray-700 rounded mx-auto mb-2"></div>
        <div class="h-5 w-10 bg-gray-700 rounded mx-auto"></div>
      </div>
    </div>
    <div v-else-if="!error" class="bg-gray-800 rounded-lg p-8 text-center text-gray-400 mb-6">
      No funnel data available.
    </div>

    <div v-if="filteredSignals.length" class="space-y-2 sm:hidden">
      <button
        v-for="s in filteredSignals"
        :key="s.id"
        class="w-full rounded-lg border border-gray-800 bg-gray-900/40 p-3 text-left text-sm transition-colors hover:bg-gray-800/60"
        :class="{ 'ring-1 ring-blue-500/60 bg-gray-800/60': expandedSignalId === s.id }"
        @click="toggleSignal(s.id)"
        :aria-expanded="expandedSignalId === s.id"
      >
        <div class="mb-2 flex items-start justify-between gap-2">
          <div class="break-all text-gray-200">{{ displayLeader(s) }}</div>
          <StatusBadge :status="s.decision" />
        </div>
        <div class="break-words text-xs text-gray-400">{{ s.market_slug }}</div>
        <div class="mt-2 grid grid-cols-2 gap-2 text-xs text-gray-400">
          <div>Side: <span class="text-gray-300">{{ s.side }}</span></div>
          <div>
            Order:
            <StatusBadge v-if="s.order_status" :status="s.order_status" />
            <span v-else class="text-gray-400">—</span>
          </div>
          <div class="col-span-2">Detected: <span class="text-gray-300">{{ new Date(s.detected_at).toLocaleString() }}</span></div>
        </div>
        <div class="mt-1 text-xs text-blue-300/80">
          {{ expandedSignalId === s.id ? 'Tap to collapse details' : 'Tap to view details' }}
        </div>
        <div v-if="expandedSignalId === s.id" class="mt-2 space-y-1 border-t border-gray-700/70 pt-2 text-xs text-gray-400">
          <div class="break-all">Wallet: <span class="text-gray-300">{{ s.wallet }}</span></div>
          <div class="break-all">Condition: <span class="text-gray-300">{{ s.condition_id }}</span></div>
          <div class="break-words">Reason: <span class="text-gray-300">{{ s.reason || '—' }}</span></div>
          <div class="break-words">Order reason: <span class="text-gray-300">{{ s.order_reason || '—' }}</span></div>
        </div>
      </button>
    </div>

    <table v-if="filteredSignals.length" class="hidden w-full text-sm sm:table">
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
        <tr v-for="s in filteredSignals" :key="s.id" class="border-b border-gray-800 text-gray-300">
          <td class="py-2">{{ displayLeader(s) }}</td>
          <td class="py-2">{{ s.market_slug }}</td>
          <td class="py-2">{{ s.side }}</td>
          <td class="py-2"><StatusBadge :status="s.decision" /></td>
          <td class="py-2">
            <StatusBadge v-if="s.order_status" :status="s.order_status" />
            <span v-else class="text-gray-400">—</span>
          </td>
          <td class="py-2 text-gray-400">{{ new Date(s.detected_at).toLocaleString() }}</td>
        </tr>
      </tbody>
    </table>
    <div v-else-if="signalQuery.trim() && !isLoading && !error" class="py-12 text-center text-gray-400">
      No signals match "{{ signalQuery }}".
    </div>
    <div v-else-if="!isLoading && !error" class="py-12 text-center text-gray-400">
      No signals detected yet.
    </div>
  </div>
</template>
