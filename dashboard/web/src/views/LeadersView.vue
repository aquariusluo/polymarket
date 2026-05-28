<script setup lang="ts">
import api from '../api/client'
import { ref } from 'vue'
import { useRefresh } from '../stores/refresh'
import type { Leader, LeaderTrade } from '../types'

const leaders = ref<Leader[]>([])
const selectedTrades = ref<LeaderTrade[]>([])
const selectedLeader = ref<string | null>(null)
const loading = ref(true)
const { lastRefreshed } = useRefresh(fetch)

async function fetch() {
  leaders.value = await api.getLeaders()
  loading.value = false
}

async function showTrades(wallet: string) {
  if (selectedLeader.value === wallet) {
    selectedLeader.value = null
    selectedTrades.value = []
    return
  }
  selectedLeader.value = wallet
  selectedTrades.value = await api.getLeaderTrades(wallet)
}
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-2xl font-bold text-white">Leaders</h1>
      <span v-if="lastRefreshed" class="text-xs text-gray-500">
        Updated {{ lastRefreshed.toLocaleTimeString() }}
      </span>
    </div>

    <div v-if="loading" class="text-gray-400">Loading...</div>

    <template v-else>
      <table class="w-full text-sm">
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
            v-for="l in leaders"
            :key="l.wallet"
            class="border-b border-gray-800 text-gray-300 cursor-pointer hover:bg-gray-800/50 transition-colors"
            :class="{ 'bg-gray-800/50': selectedLeader === l.wallet }"
            @click="showTrades(l.wallet)"
          >
            <td class="py-2">{{ l.rank }}</td>
            <td class="py-2">{{ l.name || l.pseudonym || l.wallet.slice(0, 8) }}</td>
            <td class="py-2" :class="l.pnl_snapshot >= 0 ? 'text-green-400' : 'text-red-400'">${{ l.pnl_snapshot.toFixed(2) }}</td>
            <td class="py-2">${{ l.volume_snapshot.toFixed(2) }}</td>
            <td class="py-2">{{ l.trade_count }}</td>
            <td class="py-2 text-gray-500">{{ l.last_trade_at ? new Date(l.last_trade_at).toLocaleString() : '—' }}</td>
          </tr>
        </tbody>
      </table>

      <div v-if="selectedTrades.length" class="mt-4">
        <h2 class="text-sm font-semibold text-gray-300 mb-3">
          Recent Trades — {{ selectedLeader?.slice(0, 8) }}
        </h2>
        <table class="w-full text-sm">
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
              <td class="py-2 text-gray-500">{{ new Date(t.timestamp).toLocaleString() }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>
