<script setup lang="ts">
import VChart from 'vue-echarts'

defineProps<{
  option: Record<string, any>
  autoresize?: boolean
  class?: string
}>()
</script>

<template>
  <VChart :option="option" :autoresize="autoresize ?? true" :class="$props.class" />
</template>
