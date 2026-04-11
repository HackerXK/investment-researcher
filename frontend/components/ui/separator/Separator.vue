<script setup lang="ts">
import { type HTMLAttributes } from 'vue'
import { cn } from '~/lib/utils'

const props = defineProps<{ class?: HTMLAttributes['class'] }>()
</script>

<template>
  <div role="none" :class="cn('shrink-0 bg-border h-[1px] w-full', props.class)" />
</template>
