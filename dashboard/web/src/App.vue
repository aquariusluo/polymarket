<script setup lang="ts">
import { RouterLink } from 'vue-router'

const navItems = [
  { to: '/overview', label: 'Overview', icon: '⌂' },
  { to: '/portfolio', label: 'Portfolio', icon: '💰' },
  { to: '/signals', label: 'Signals', icon: '📦' },
  { to: '/leaders', label: 'Leaders', icon: '🐺' },
  { to: '/pipeline', label: 'Pipeline', icon: '⚙' },
]
</script>

<template>
  <div class="flex min-h-screen bg-gray-950 text-gray-100">
    <aside class="w-56 bg-gray-900 border-r border-gray-800 flex flex-col">
      <div class="px-5 py-4 border-b border-gray-800">
        <h1 class="text-lg font-bold text-white tracking-tight">Polymarket</h1>
        <p class="text-xs text-gray-500 mt-0.5">Copy-Trade Monitor</p>
      </div>
      <nav class="flex-1 py-2">
        <RouterLink
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="flex items-center gap-3 px-5 py-2.5 text-sm hover:bg-gray-800 transition-colors text-gray-400"
          :class="$route.path === item.to ? 'bg-gray-800 text-white' : ''"
        >
          <span class="text-lg">{{ item.icon }}</span>
          {{ item.label }}
        </RouterLink>
      </nav>
      <div class="px-5 py-3 border-t border-gray-800 text-xs text-gray-600">
        manual_confirm mode
      </div>
    </aside>
    <main class="flex-1 overflow-auto p-6">
      <router-view />
    </main>
  </div>
</template>
