<script setup lang="ts">
import { computed } from 'vue'
import { Line } from 'vue-chartjs'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Tooltip,
  Filler,
  type ChartOptions,
} from 'chart.js'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Filler)

const props = defineProps<{
  labels: string[]
  datasets: { label: string; data: number[]; borderColor?: string; backgroundColor?: string }[]
}>()

const options: ChartOptions<'line'> = {
  responsive: true,
  maintainAspectRatio: false,
  interaction: { mode: 'index', intersect: false },
  plugins: {
    legend: { display: true, labels: { color: '#9ca3af', boxWidth: 12 } },
    tooltip: { backgroundColor: '#1f2937', titleColor: '#f3f4f6', bodyColor: '#d1d5db' },
  },
  scales: {
    x: { grid: { color: '#1f2937' }, ticks: { color: '#6b7280', maxTicksLimit: 8 } },
    y: { grid: { color: '#1f2937' }, ticks: { color: '#6b7280' } },
  },
}

const chartData = computed(() => ({
  labels: props.labels,
  datasets: props.datasets.map((d) => ({
    label: d.label,
    data: d.data,
    borderColor: d.borderColor ?? '#a78bfa',
    backgroundColor: d.backgroundColor ?? 'rgba(167, 139, 250, 0.1)',
    fill: true,
    tension: 0.3,
    pointRadius: 0,
    pointHitRadius: 10,
  })),
}))
</script>

<template>
  <div class="h-64">
    <Line :options="options" :data="chartData" />
  </div>
</template>
