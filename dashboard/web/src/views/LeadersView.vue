<script setup lang="ts">
import api from '../api/client'
import { computed, ref, watch } from 'vue'
import { useRefresh } from '../stores/refresh'
import type { Leader, LeaderTrade } from '../types'

const leaders = ref<Leader[]>([])
const selectedTrades = ref<LeaderTrade[]>([])
const selectedLeader = ref<string | null>(null)
const tradeError = ref<string | null>(null)
const leaderQuery = ref('')
const { lastRefreshed, isLoading, isRefetching, error, refresh } = useRefresh(fetch)

function shortWallet(wallet: string) {
  return `${wallet.slice(0, 6)}...${wallet.slice(-4)}`
}

function displayLeaderName(l: Leader) {
  return l.name || l.pseudonym || shortWallet(l.wallet)
}

function formatLocalTime(value: string | null) {
  return value ? new Date(value).toLocaleString() : '—'
}

const filteredLeaders = computed(() => {
  const q = leaderQuery.value.trim().toLowerCase()
  if (!q) return leaders.value
  return leaders.value.filter((l) => {
    const name = (l.name || '').toLowerCase()
    const pseudonym = (l.pseudonym || '').toLowerCase()
    const wallet = l.wallet.toLowerCase()
    return name.includes(q) || pseudonym.includes(q) || wallet.includes(q)
  })
})

watch(filteredLeaders, (items) => {
  if (selectedLeader.value && !items.some((l) => l.wallet === selectedLeader.value)) {
    selectedLeader.value = null
    selectedTrades.value = []
    tradeError.value = null
  }
})

async function fetch() {
  leaders.value = await api.getLeaders()
}

async function showTrades(wallet: string) {
  if (selectedLeader.value === wallet) {
    selectedLeader.value = null
    selectedTrades.value = []
    tradeError.value = null
    return
  }
  selectedLeader.value = wallet
  tradeError.value = null
  try {
    selectedTrades.value = await api.getLeaderTrades(wallet)
  } catch (err) {
    selectedLeader.value = null
    selectedTrades.value = []
    tradeError.value = err instanceof Error ? err.message : 'Failed to load leader trades'
  }
}
</script>

<template>
  <div class="min-w-0">
    <div class="sticky top-[var(--mobile-nav-offset,6.5rem)] z-20 mb-3 rounded-lg border border-gray-800/80 bg-gray-950/90 px-3 py-2 backdrop-blur sm:hidden">
      <div class="flex items-center justify-between">
        <h1 class="text-lg font-bold text-white">Leaders</h1>
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
        v-model="leaderQuery"
        type="text"
        placeholder="Search leader or wallet..."
        class="mt-2 min-h-11 w-full rounded-md border border-gray-700 bg-gray-900 px-3 py-2 text-xs text-gray-200 placeholder:text-gray-400 focus:border-blue-500 focus:outline-none"
      />
    </div>

    <div class="mb-5 hidden flex-col gap-2 sm:mb-6 sm:flex sm:flex-row sm:items-center sm:justify-between">
      <div class="flex items-center gap-3">
        <h1 class="text-xl font-bold text-white sm:text-2xl">Leaders</h1>
        <span v-if="isRefetching" class="text-xs text-blue-400 animate-pulse">Refreshing...</span>
      </div>
      <div class="flex flex-col sm:items-end">
        <input
          v-model="leaderQuery"
          type="text"
          placeholder="Search leader or wallet..."
          class="hidden w-64 rounded-md border border-gray-700 bg-gray-900 min-h-11 px-2.5 py-1.5 text-xs text-gray-200 placeholder:text-gray-400 focus:border-blue-500 focus:outline-none sm:block"
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
    <div v-if="error && !leaders.length" class="mb-6 flex flex-col gap-3 rounded-lg border border-red-800 bg-red-900/20 p-4 text-red-400 sm:flex-row sm:items-center sm:justify-between">
      <span class="break-words">Failed to load leaders. {{ error.message }}</span>
      <button @click="refresh" class="min-h-11 rounded bg-red-800 px-3 py-2 text-xs text-white transition hover:bg-red-700">
        Retry
      </button>
    </div>

    <div v-if="isLoading" class="text-gray-400 animate-pulse py-8 text-center">
      Loading leaders data...
    </div>

    <template v-else-if="filteredLeaders.length">
      <div class="space-y-3 sm:hidden">
        <button
          v-for="l in filteredLeaders"
          :key="l.wallet"
          class="w-full rounded-lg border border-gray-800 bg-gray-900/50 p-3 text-left transition-colors hover:bg-gray-800/60"
          :class="{ 'ring-1 ring-blue-500/60 bg-gray-800/60': selectedLeader === l.wallet }"
          @click="showTrades(l.wallet)"
          :aria-expanded="selectedLeader === l.wallet"
        >
          <div class="mb-1 flex items-center justify-between">
            <span class="text-xs text-gray-400">#{{ l.rank }}</span>
            <span class="text-sm font-semibold" :class="l.pnl_snapshot >= 0 ? 'text-green-400' : 'text-red-400'">
              ${{ l.pnl_snapshot.toFixed(2) }}
            </span>
          </div>
          <div class="break-all text-sm text-gray-200">{{ displayLeaderName(l) }}</div>
          <div class="mt-1 text-xs text-gray-400">{{ shortWallet(l.wallet) }}</div>
          <div class="mt-2 grid grid-cols-2 gap-2 text-xs text-gray-400">
            <div>Volume: <span class="text-gray-300">${{ l.volume_snapshot.toFixed(2) }}</span></div>
            <div>Trades: <span class="text-gray-300">{{ l.trade_count }}</span></div>
          </div>
          <div class="mt-1 text-xs text-gray-400">
            Last: {{ formatLocalTime(l.last_trade_at) }}
          </div>
          <div class="mt-1 text-xs text-blue-300/80">
            {{ selectedLeader === l.wallet ? 'Tap to collapse trades' : 'Tap to view recent trades' }}
          </div>

          <div v-if="selectedLeader === l.wallet && selectedTrades.length" class="mt-3 space-y-2 border-t border-gray-700/70 pt-3">
            <div
              v-for="t in selectedTrades"
              :key="t.id"
              class="rounded-md border border-gray-700 bg-gray-900/60 p-2.5"
            >
              <div class="break-words text-xs text-gray-200">{{ t.market_slug || t.market_title }}</div>
              <div class="mt-1 grid grid-cols-2 gap-2 text-[11px] text-gray-400">
                <div>Side: <span class="text-gray-300">{{ t.side || '—' }}</span></div>
                <div>Price: <span class="text-gray-300">{{ t.price || '—' }}</span></div>
                <div>Size: <span class="text-gray-300">{{ t.size || '—' }}</span></div>
                <div>Time: <span class="text-gray-300">{{ formatLocalTime(t.timestamp) }}</span></div>
              </div>
            </div>
          </div>
          <div
            v-else-if="selectedLeader === l.wallet && !selectedTrades.length"
            class="mt-3 border-t border-gray-700/70 pt-3 text-xs text-gray-400"
          >
            No recent trades found.
          </div>
        </button>
      </div>

      <table class="hidden w-full text-sm sm:table">
        <thead>
          <tr class="text-left text-gray-400 border-b border-gray-700">
            <th class="pb-2">Rank</th>
            <th class="pb-2">Name</th>
            <th class="pb-2">PnL</th>
            <th class="pb-2">Volume</th>
            <th class="pb-2">Trades</th>
            <th class="pb-2">Last Trade</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="l in filteredLeaders"
            :key="l.wallet"
            class="border-b border-gray-800 text-gray-300 cursor-pointer hover:bg-gray-800/50 transition-colors"
            :class="{ 'bg-gray-800/50': selectedLeader === l.wallet }"
            @click="showTrades(l.wallet)"
          >
            <td class="py-2">{{ l.rank }}</td>
            <td class="py-2">{{ displayLeaderName(l) }}</td>
            <td class="py-2" :class="l.pnl_snapshot >= 0 ? 'text-green-400' : 'text-red-400'">${{ l.pnl_snapshot.toFixed(2) }}</td>
            <td class="py-2">${{ l.volume_snapshot.toFixed(2) }}</td>
            <td class="py-2">{{ l.trade_count }}</td>
            <td class="py-2 text-gray-400">{{ formatLocalTime(l.last_trade_at) }}</td>
          </tr>
        </tbody>
      </table>

      <div v-if="tradeError" class="mt-4 bg-red-900/20 border border-red-800 text-red-400 p-3 rounded-lg text-xs">
        {{ tradeError }}
      </div>
      <div v-else-if="selectedTrades.length" class="mt-4 hidden sm:block">
        <h2 class="text-sm font-semibold text-gray-300 mb-3">
          Recent Trades — {{ selectedLeader ? shortWallet(selectedLeader) : '' }}
        </h2>
        <table class="hidden w-full text-sm sm:table">
          <thead>
            <tr class="text-left text-gray-400 border-b border-gray-700">
              <th class="pb-2">Market</th>
              <th class="pb-2">Side</th>
              <th class="pb-2">Size</th>
              <th class="pb-2">Price</th>
              <th class="pb-2">Time</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in selectedTrades" :key="t.id" class="border-b border-gray-800 text-gray-300">
              <td class="py-2">{{ t.market_slug || t.market_title }}</td>
              <td class="py-2">{{ t.side }}</td>
              <td class="py-2">{{ t.size }}</td>
              <td class="py-2">{{ t.price }}</td>
              <td class="py-2 text-gray-400">{{ formatLocalTime(t.timestamp) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
    <div v-else-if="leaderQuery.trim() && !isLoading && !error" class="text-center py-12 text-gray-400">
      No leaders match "{{ leaderQuery }}".
    </div>
    <div v-else-if="!error" class="text-center py-12 text-gray-400">
      No leaders tracked yet.
    </div>
  </div>
</template>
