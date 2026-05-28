import { ref, onMounted, onUnmounted } from 'vue'

export function useRefresh(fetchFn: () => Promise<void>, intervalMs = 30_000) {
  const lastRefreshed = ref<Date | null>(null)
  const isPolling = ref(false)
  let timer: ReturnType<typeof setInterval> | null = null

  async function fetch() {
    try {
      await fetchFn()
      lastRefreshed.value = new Date()
    } catch {
      // retry on next interval
    }
  }

  function startPolling() {
    if (isPolling.value) return
    isPolling.value = true
    fetch()
    timer = setInterval(fetch, intervalMs)
  }

  function stopPolling() {
    isPolling.value = false
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  onMounted(() => startPolling())
  onUnmounted(() => stopPolling())

  return { lastRefreshed, isPolling, startPolling, stopPolling }
}
