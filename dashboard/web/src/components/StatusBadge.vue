<script setup lang="ts">
const props = defineProps<{
  status: string
}>()

const colorMap: Record<string, string> = {
  success: 'bg-green-900/50 text-green-400',
  error: 'bg-red-900/50 text-red-400',
  running: 'bg-yellow-900/50 text-yellow-400',
  pending: 'bg-gray-700 text-gray-400',
  accepted: 'bg-green-900/50 text-green-400',
  rejected: 'bg-red-900/50 text-red-400',
  filled: 'bg-blue-900/50 text-blue-400',
  hold: 'bg-yellow-900/50 text-yellow-400',
  go: 'bg-green-900/50 text-green-400',
}

const classes = colorMap[props.status.toLowerCase()] ?? 'bg-gray-700 text-gray-300'
</script>

<template>
  <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium" :class="classes">
    {{ status }}
  </span>
</template>
