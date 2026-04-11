<script setup lang="ts">
import { computed } from 'vue'
import { TrendingUp, TrendingDown, DollarSign, BarChart3, Users, Activity } from 'lucide-vue-next'
import { Card, CardContent } from '~/components/ui/card'
import type { FinancialsResponse } from '~/lib/api'
import { fmtCurrency, fmtCount, fmtPercent, deltaColor } from '~/lib/formatters'

const props = defineProps<{ data: FinancialsResponse; ticker: string }>()

interface KpiItem {
  label: string
  value: string
  change: number | null
  changeLabel: string
  icon: any
}

const kpis = computed<KpiItem[]>(() => {
  const d = props.data
  const summary = d.summary || []
  const growth = d.growth || []
  const ttm = d.ttm || {}

  // summary records: { metric_type, value, period_end }
  function latestVal(key: string): number | null {
    const rows = summary
      .filter((r: any) => r.metric_type === key)
      .sort((a: any, b: any) => (a.period_end || '').localeCompare(b.period_end || ''))
    const last = rows.length ? rows[rows.length - 1] : null
    return last ? (last as any).value : null
  }

  // growth records: { period_end, metric1, metric2, ... } — values already in %
  function latestGrowth(key: string): number | null {
    if (!growth.length) return null
    const sorted = [...growth].sort((a: any, b: any) =>
      (a.period_end || '').localeCompare(b.period_end || ''),
    )
    const last = sorted[sorted.length - 1] as any
    const v = last?.[key]
    return v != null ? v / 100 : null // convert back to fraction for fmtPercent
  }

  return [
    {
      label: 'Revenue',
      value: fmtCurrency(ttm.revenue ?? latestVal('revenue')),
      change: latestGrowth('revenue'),
      changeLabel: 'YoY',
      icon: DollarSign,
    },
    {
      label: 'Net Income',
      value: fmtCurrency(ttm.net_income ?? latestVal('net_income')),
      change: latestGrowth('net_income'),
      changeLabel: 'YoY',
      icon: BarChart3,
    },
    {
      label: 'EPS (Diluted)',
      value: `$${(ttm.eps_diluted ?? latestVal('eps_diluted') ?? 0).toFixed(2)}`,
      change: latestGrowth('eps_diluted'),
      changeLabel: 'YoY',
      icon: Activity,
    },
    {
      label: 'Shares Outstanding',
      value: fmtCount(ttm.common_shares_outstanding ?? latestVal('common_shares_outstanding')),
      change: latestGrowth('common_shares_outstanding'),
      changeLabel: 'YoY',
      icon: Users,
    },
  ]
})
</script>

<template>
  <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
    <Card v-for="kpi in kpis" :key="kpi.label" class="group hover:shadow-md transition-shadow">
      <CardContent class="p-5">
        <div class="flex items-center justify-between mb-3">
          <span class="text-xs font-medium text-muted-foreground uppercase tracking-wide">{{ kpi.label }}</span>
          <component :is="kpi.icon" class="h-4 w-4 text-muted-foreground/60" />
        </div>
        <div class="text-2xl font-bold tracking-tight mb-1">{{ kpi.value }}</div>
        <div v-if="kpi.change != null" class="flex items-center gap-1 text-xs">
          <component
            :is="kpi.change >= 0 ? TrendingUp : TrendingDown"
            class="h-3 w-3"
            :class="deltaColor(kpi.change)"
          />
          <span :class="deltaColor(kpi.change)" class="font-medium">
            {{ fmtPercent(kpi.change) }}
          </span>
          <span class="text-muted-foreground">{{ kpi.changeLabel }}</span>
        </div>
      </CardContent>
    </Card>
  </div>
</template>
