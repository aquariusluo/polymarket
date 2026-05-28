<script setup lang="ts">
defineProps<{
  label: string
  value: string
  color?: string
}>()
</script>

<template>
  <div class="bg-gray-800 rounded-lg p-4">
    <div class="text-xs text-gray-400 mb-1">{{ label }}</div>
    <div class="text-xl font-bold" :class="color ?? 'text-white'">{{ value }}</div>
  </div>
</template>
