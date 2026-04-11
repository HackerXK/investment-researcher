<script setup lang="ts">
import { computed } from 'vue'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '~/components/ui/card'
import type { HealthResponse } from '~/lib/api'
import { radarChart, lineChart } from '~/lib/charts'
import { fmtRatio, fmtPercent } from '~/lib/formatters'

const props = defineProps<{ data: HealthResponse; ticker: string }>()

interface HealthMetric {
  label: string
  key: string
  value: number | null
  ttm: number | null
  format: string
  score: number // 0-100 normalised
}

const healthMetrics = computed<HealthMetric[]>(() => {
  const latest = props.data.ratios_latest || {}
  const ttm = props.data.ratios_ttm || {}

  function norm(val: number | null, lower: number, upper: number): number {
    if (val == null) return 0
    const clamped = Math.max(lower, Math.min(upper, val))
    return ((clamped - lower) / (upper - lower)) * 100
  }

  return [
    {
      label: 'Current Ratio',
      key: 'current_ratio',
      value: latest.current_ratio ?? null,
      ttm: ttm.current_ratio ?? null,
      format: 'multiple',
      score: norm(latest.current_ratio ?? null, 0, 3),
    },
    {
      label: 'Debt/Equity',
      key: 'financial_leverage_ratio',
      value: latest.financial_leverage_ratio ?? null,
      ttm: ttm.financial_leverage_ratio ?? null,
      format: 'multiple',
      score: Math.max(0, 100 - norm(latest.financial_leverage_ratio ?? null, 0, 10) * 100 / 100),
    },
    {
      label: 'Interest Coverage',
      key: 'interest_coverage_ratio',
      value: latest.interest_coverage_ratio ?? null,
      ttm: ttm.interest_coverage_ratio ?? null,
      format: 'multiple',
      score: norm(latest.interest_coverage_ratio ?? ttm.interest_coverage_ratio ?? null, 0, 20),
    },
    {
      label: 'Gross Margin',
      key: 'gross_profit_margin',
      value: latest.gross_profit_margin ?? null,
      ttm: ttm.gross_profit_margin ?? null,
      format: 'pct',
      score: norm(latest.gross_profit_margin ?? null, 0, 1) ,
    },
    {
      label: 'ROE',
      key: 'return_on_equity',
      value: latest.return_on_equity ?? null,
      ttm: ttm.return_on_equity ?? null,
      format: 'pct',
      score: norm(latest.return_on_equity ?? null, 0, 0.4) ,
    },
    {
      label: 'FCF/OCF',
      key: 'free_cash_flow_to_operating_cash_flow_ratio',
      value: latest.free_cash_flow_to_operating_cash_flow_ratio ?? null,
      ttm: ttm.free_cash_flow_to_operating_cash_flow_ratio ?? null,
      format: 'pct',
      score: norm(latest.free_cash_flow_to_operating_cash_flow_ratio ?? null, 0, 1) ,
    },
  ]
})

const radar = computed(() => {
  const m = healthMetrics.value
  return radarChart(
    m.map(h => h.label),
    m.map(h => h.score),
    { name: props.ticker, maxVal: 100 },
  )
})

const revenueGrowthChart = computed(() => {
  const g = (props.data.revenue_growth || []) as Array<Record<string, any>>
  if (!g.length) return null
  const sorted = [...g].sort((a, b) => String(a.period_end).localeCompare(String(b.period_end)))
  return lineChart(
    sorted.map(r => String(r.period_end).slice(0, 10)),
    [{ name: 'Revenue Growth', data: sorted.map(r => (r.revenue != null ? +Number(r.revenue).toFixed(2) : null)) }],
    { ySuffix: '%' },
  )
})
</script>

<template>
  <div class="space-y-6">
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <!-- Radar chart -->
      <Card>
        <CardHeader class="pb-2">
          <CardTitle class="text-base">Financial Health Radar</CardTitle>
          <CardDescription>Normalised scores (0–100) across key dimensions</CardDescription>
        </CardHeader>
        <CardContent>
          <EChart :option="radar" autoresize class="h-80" />
        </CardContent>
      </Card>

      <!-- Revenue growth -->
      <Card v-if="revenueGrowthChart">
        <CardHeader class="pb-2">
          <CardTitle class="text-base">Revenue Growth Trend</CardTitle>
        </CardHeader>
        <CardContent>
          <EChart :option="revenueGrowthChart" autoresize class="h-80" />
        </CardContent>
      </Card>
    </div>

    <!-- Health metric cards -->
    <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
      <Card v-for="m in healthMetrics" :key="m.key">
        <CardContent class="p-4 text-center">
          <div class="text-xs text-muted-foreground mb-2">{{ m.label }}</div>
          <div class="text-xl font-bold tabular-nums mb-1">
            {{ fmtRatio(m.value, m.format) }}
          </div>
          <div v-if="m.ttm != null" class="text-xs text-muted-foreground">
            TTM: {{ fmtRatio(m.ttm, m.format) }}
          </div>
          <!-- Score bar -->
          <div class="mt-3 h-1.5 rounded-full bg-muted overflow-hidden">
            <div
              class="h-full rounded-full transition-all duration-500"
              :class="m.score >= 60 ? 'bg-gain' : m.score >= 30 ? 'bg-amber-500' : 'bg-loss'"
              :style="{ width: `${m.score}%` }"
            />
          </div>
        </CardContent>
      </Card>
    </div>
  </div>
</template>
