<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

const navItems = [
  { to: '/overview', label: 'Overview', icon: '⌂' },
  { to: '/portfolio', label: 'Portfolio', icon: '💰' },
  { to: '/signals', label: 'Signals', icon: '📦' },
  { to: '/leaders', label: 'Leaders', icon: '🐺' },
  { to: '/pipeline', label: 'Pipeline', icon: '⚙' },
]

const routeModules: Record<string, () => Promise<unknown>> = {
  '/overview': () => import('./views/OverviewView.vue'),
  '/portfolio': () => import('./views/PortfolioView.vue'),
  '/signals': () => import('./views/SignalsView.vue'),
  '/leaders': () => import('./views/LeadersView.vue'),
  '/pipeline': () => import('./views/PipelineView.vue'),
}

const route = useRoute()
const appShell = ref<HTMLElement | null>(null)
const navScroller = ref<HTMLElement | null>(null)
const showBackToTop = ref(false)

function preloadRoute(path: string) {
  routeModules[path]?.()
}

function centerActiveNavItem() {
  const scroller = navScroller.value
  if (!scroller) return
  const active = scroller.querySelector<HTMLElement>('[data-active="true"]')
  if (!active) return
  active.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' })
}

function updateBackToTopVisibility() {
  showBackToTop.value = window.scrollY > 280
}

function scrollToTop() {
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function updateMobileNavOffset() {
  const shell = appShell.value
  if (!shell) return
  if (window.innerWidth >= 768) {
    shell.style.setProperty('--mobile-nav-offset', '0px')
    return
  }
  const nav = shell.querySelector<HTMLElement>('aside')
  const offset = nav ? Math.ceil(nav.getBoundingClientRect().height + 8) : 104
  shell.style.setProperty('--mobile-nav-offset', `${offset}px`)
}

watch(
  () => route.path,
  async () => {
    await nextTick()
    centerActiveNavItem()
    updateMobileNavOffset()
    showBackToTop.value = false
  },
)

onMounted(() => {
  centerActiveNavItem()
  updateBackToTopVisibility()
  updateMobileNavOffset()
  window.addEventListener('scroll', updateBackToTopVisibility, { passive: true })
  window.addEventListener('resize', updateMobileNavOffset, { passive: true })
})

onUnmounted(() => {
  window.removeEventListener('scroll', updateBackToTopVisibility)
  window.removeEventListener('resize', updateMobileNavOffset)
})
</script>

<template>
  <div ref="appShell" class="min-h-screen bg-gray-950 text-gray-100 md:flex">
    <aside class="sticky top-0 z-30 w-full border-b border-gray-800/90 bg-gray-900/95 backdrop-blur supports-[backdrop-filter]:bg-gray-900/80 md:static md:w-56 md:border-b-0 md:border-r md:bg-gray-900 md:backdrop-blur-none md:flex md:min-h-screen md:flex-col">
      <div class="px-4 pb-3 pt-[max(env(safe-area-inset-top),0.5rem)] md:px-5 md:py-4 md:border-b md:border-gray-800">
        <h1 class="text-base font-bold text-white tracking-tight md:text-lg">Polymarket</h1>
        <p class="mt-0.5 text-xs text-gray-400">Copy-Trade Monitor</p>
      </div>
      <nav ref="navScroller" class="overflow-x-auto px-2 py-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden md:flex-1 md:overflow-visible md:px-0">
        <div class="flex min-w-max snap-x snap-mandatory gap-1 md:block md:min-w-0">
        <RouterLink
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="min-h-11 snap-center flex items-center gap-2 rounded-md px-3 py-2 text-sm text-gray-400 transition-colors hover:bg-gray-800 md:mx-1 md:min-h-0 md:rounded-none md:px-5 md:py-2.5"
          :class="$route.path === item.to ? 'bg-gray-800 text-white' : ''"
          :data-active="$route.path === item.to ? 'true' : 'false'"
          @mouseenter="preloadRoute(item.to)"
        >
          <span class="text-base md:text-lg">{{ item.icon }}</span>
          {{ item.label }}
        </RouterLink>
        </div>
      </nav>
      <div class="hidden border-t border-gray-800 px-5 py-3 text-xs text-gray-600 md:block">
        manual_confirm mode
      </div>
    </aside>
    <main class="min-w-0 flex-1 overflow-x-auto px-4 pb-[max(env(safe-area-inset-bottom),1rem)] pt-4 md:p-6">
      <router-view />
    </main>

    <button
      v-if="showBackToTop"
      class="fixed bottom-[max(env(safe-area-inset-bottom),1rem)] right-4 z-40 inline-flex h-11 w-11 items-center justify-center rounded-full border border-gray-700 bg-gray-800/90 text-gray-100 shadow-lg backdrop-blur transition hover:bg-gray-700 md:hidden"
      aria-label="Back to top"
      @click="scrollToTop"
    >
      ↑
    </button>
  </div>
</template>
