<script setup lang="ts">
import { type HTMLAttributes, computed } from 'vue'
import { TabsList as TabsListPrimitive, type TabsListProps } from 'radix-vue'
import { cn } from '~/lib/utils'

const props = defineProps<TabsListProps & { class?: HTMLAttributes['class'] }>()
const delegatedProps = computed(() => {
  const { class: _, ...p } = props
  return p
})
</script>

<template>
  <TabsListPrimitive
    v-bind="delegatedProps"
    :class="cn('inline-flex h-10 items-center justify-center rounded-md bg-muted p-1 text-muted-foreground', props.class)"
  >
    <slot />
  </TabsListPrimitive>
</template>
