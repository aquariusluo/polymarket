import { ref, onMounted, onUnmounted } from 'vue'

export function useRefresh(fetchFn: () => Promise<void>, intervalMs = 30_000) {
  const lastRefreshed = ref<Date | null>(null)
  const isLoading = ref(true)
  const isRefetching = ref(false)
  const error = ref<Error | null>(null)
  const isPolling = ref(false)
  const isFetching = ref(false)
  let timer: ReturnType<typeof setInterval> | null = null

  async function fetch() {
    if (isFetching.value) return
    isFetching.value = true

    const isInitial = !lastRefreshed.value && !error.value
    if (isInitial) {
      isLoading.value = true
    } else {
      isRefetching.value = true
    }

    error.value = null

    try {
      await fetchFn()
      lastRefreshed.value = new Date()
    } catch (e) {
      console.error('Refresh failed:', e)
      error.value = e instanceof Error ? e : new Error(String(e))
    } finally {
      isFetching.value = false
      isLoading.value = false
      isRefetching.value = false
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

  return { 
    lastRefreshed, 
    isLoading, 
    isRefetching, 
    error, 
    isPolling, 
    startPolling, 
    stopPolling,
    refresh: fetch 
  }
}
