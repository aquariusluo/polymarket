<script setup lang="ts">
defineProps<{
  label: string
  value: string
  color?: string
}>()
</script>

<template>
  <div class="rounded-lg bg-gray-800 p-3 sm:p-4">
    <div class="mb-1 text-xs leading-tight text-gray-300">{{ label }}</div>
    <div class="text-lg font-bold sm:text-xl" :class="color ?? 'text-white'">{{ value }}</div>
  </div>
</template>
