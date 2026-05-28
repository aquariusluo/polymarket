<script setup lang="ts">
import api from '../api/client'
import { ref } from 'vue'
import { useRefresh } from '../stores/refresh'
import StatusBadge from '../components/StatusBadge.vue'
import type { JobRun, MonitorEvent } from '../types'

const runs = ref<JobRun[]>([])
const monitorLog = ref<MonitorEvent[]>([])
const loading = ref(true)
const { lastRefreshed } = useRefresh(fetch)

async function fetch() {
  const [r, m] = await Promise.all([api.getJobRuns(), api.getMonitorLog()])
  runs.value = r
  monitorLog.value = m
  loading.value = false
}

const fmtDuration = (ms: number | null) => ms != null ? `${(ms / 1000).toFixed(1)}s` : '—'
const fmtTime = (s: string | null) => s ? new Date(s).toLocaleString() : '—'
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-2xl font-bold text-white">Pipeline</h1>
      <span v-if="lastRefreshed" class="text-xs text-gray-500">
        Updated {{ lastRefreshed.toLocaleTimeString() }}
      </span>
    </div>

    <div v-if="loading" class="text-gray-400">Loading...</div>

    <template v-else>
      <h2 class="text-sm font-semibold text-gray-300 mb-3">Job Runs</h2>
      <div class="overflow-x-auto mb-8">
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
              <td class="py-2 text-gray-500">{{ fmtTime(r.finished_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <h2 class="text-sm font-semibold text-gray-300 mb-3">Monitor Log</h2>
      <div class="space-y-1 max-h-96 overflow-y-auto">
        <div
          v-for="(entry, i) in monitorLog"
          :key="i"
          class="flex gap-3 text-xs font-mono bg-gray-900 rounded px-3 py-2"
        >
          <span class="text-gray-500 shrink-0">{{ fmtTime(entry.timestamp) }}</span>
          <span class="text-gray-300">{{ entry.event }}</span>
          <span v-if="entry.stderr" class="text-red-400 truncate">{{ entry.stderr }}</span>
        </div>
      </div>
    </template>
  </div>
</template>
