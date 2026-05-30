<script setup lang="ts">
import api from '../api/client'
import { ref } from 'vue'
import { useRefresh } from '../stores/refresh'
import StatusBadge from '../components/StatusBadge.vue'
import type { JobRun, MonitorEvent } from '../types'

const runs = ref<JobRun[]>([])
const monitorLog = ref<MonitorEvent[]>([])
const { lastRefreshed, isLoading, isRefetching, error, refresh } = useRefresh(fetch)

async function fetch() {
  const [r, m] = await Promise.all([api.getJobRuns(), api.getMonitorLog()])
  runs.value = r
  monitorLog.value = m
}

const fmtDuration = (s: number | null) => s != null ? `${s.toFixed(1)}s` : '—'
const fmtTime = (s: string | null) => s ? new Date(s).toLocaleString() : '—'
</script>

<template>
  <div class="min-w-0">
    <div class="mb-5 flex flex-col gap-2 sm:mb-6 sm:flex-row sm:items-center sm:justify-between">
      <div class="flex items-center gap-4">
        <h1 class="text-xl font-bold text-white sm:text-2xl">Pipeline</h1>
        <span v-if="isRefetching" class="text-xs text-blue-400 animate-pulse">Refreshing...</span>
      </div>
      <div class="flex flex-col sm:items-end">
        <span v-if="lastRefreshed" class="text-xs text-gray-400">
          Updated {{ lastRefreshed.toLocaleTimeString() }}
        </span>
        <button v-if="error" @click="refresh" class="min-h-11 px-3 py-2 text-xs text-red-400 underline hover:text-red-300">
          Retry
        </button>
      </div>
    </div>

    <!-- Error Alert -->
    <div v-if="error && !runs.length" class="mb-6 flex flex-col gap-3 rounded-lg border border-red-800 bg-red-900/20 p-4 text-red-400 sm:flex-row sm:items-center sm:justify-between">
      <span class="break-words">Failed to load pipeline data. {{ error.message }}</span>
      <button @click="refresh" class="min-h-11 rounded bg-red-800 px-3 py-2 text-xs text-white transition hover:bg-red-700">
        Retry
      </button>
    </div>

    <div v-if="isLoading" class="text-gray-400 animate-pulse py-8 text-center">
      Loading pipeline status...
    </div>

    <template v-else-if="runs.length || monitorLog.length">
      <h2 v-if="runs.length" class="mb-3 text-sm font-semibold text-gray-300">Job Runs</h2>
      <div v-if="runs.length" class="mb-4 space-y-2 sm:hidden">
        <div
          v-for="r in runs"
          :key="r.id"
          class="rounded-lg border border-gray-800 bg-gray-900/40 p-3 text-xs text-gray-300"
        >
          <div class="mb-2 flex items-center justify-between gap-2">
            <span class="font-mono break-all">{{ r.job_name }}</span>
            <StatusBadge :status="r.status" />
          </div>
          <div class="grid grid-cols-2 gap-2 text-gray-400">
            <div>Duration: <span class="text-gray-300">{{ fmtDuration(r.duration) }}</span></div>
            <div>Inserted: <span class="text-gray-300">{{ r.inserted_count }}</span></div>
            <div>Skipped: <span class="text-gray-300">{{ r.skipped_count }}</span></div>
            <div>Finished: <span class="text-gray-300">{{ fmtTime(r.finished_at) }}</span></div>
          </div>
        </div>
      </div>
      <div v-if="runs.length" class="mb-8 hidden overflow-x-auto sm:block">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-left text-gray-400 border-b border-gray-700">
              <th class="pb-2">Job</th>
              <th class="pb-2">Status</th>
              <th class="pb-2">Duration</th>
              <th class="pb-2">Inserted</th>
              <th class="pb-2">Skipped</th>
              <th class="pb-2">Finished</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in runs" :key="r.id" class="border-b border-gray-800 text-gray-300">
              <td class="py-2 font-mono text-xs">{{ r.job_name }}</td>
              <td class="py-2"><StatusBadge :status="r.status" /></td>
              <td class="py-2">{{ fmtDuration(r.duration) }}</td>
              <td class="py-2">{{ r.inserted_count }}</td>
              <td class="py-2">{{ r.skipped_count }}</td>
              <td class="py-2 text-gray-400">{{ fmtTime(r.finished_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <h2 v-if="monitorLog.length" class="mb-3 text-sm font-semibold text-gray-300">Monitor Log</h2>
      <div v-if="monitorLog.length" class="space-y-1 max-h-96 overflow-y-auto overflow-x-hidden">
        <div
          v-for="(entry, i) in monitorLog"
          :key="i"
          class="flex gap-3 text-xs font-mono bg-gray-900 rounded px-3 py-2"
        >
          <span class="text-gray-400 shrink-0">{{ fmtTime(entry.timestamp) }}</span>
          <span class="text-gray-300">{{ entry.event }}</span>
          <span v-if="entry.stderr" class="text-red-400 truncate">{{ entry.stderr }}</span>
        </div>
      </div>
    </template>
    <div v-else-if="!error" class="text-center py-12 text-gray-400 bg-gray-800 rounded-lg">
      No pipeline activity recorded yet.
    </div>
  </div>
</template>
