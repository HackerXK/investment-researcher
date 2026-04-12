<script setup lang="ts">
import { computed } from 'vue'
import { Card, CardContent, CardHeader, CardTitle } from '~/components/ui/card'
import type { FinancialsResponse } from '~/lib/api'
import { barChart, lineChart } from '~/lib/charts'

const props = defineProps<{ data: FinancialsResponse; ticker: string }>()

// Growth rates chart — records have period_end + metric columns (already %)
const growthChart = computed(() => {
  const g = props.data.growth || []
  if (!g.length) return null

  const metricKeys = ['revenue', 'gross_profit', 'operating_income', 'net_income']
  const periods = g.map((r: any) => (r.period_end || '').slice(0, 10))

  const series = metricKeys
    .filter(key => g[0][key] !== undefined)
    .map(key => ({
      name: key.replace(/_/g, ' '),
      data: g.map((r: any) => {
        const v = r[key]
        return v != null ? +v.toFixed(2) : null // already in %
      }),
    }))

  if (!series.length) return null
  return barChart(periods, series, { yPrefix: '' })
})

// Margins chart from margins_pivot (index=periods, columns=metrics)
const marginsChart = computed(() => {
  const mp = props.data.margins_pivot
  if (!mp || !mp.columns.length) return null

  const revCI = mp.columns.indexOf('revenue')
  if (revCI < 0) return null
  const rev = mp.data.map(row => row[revCI])
  const periods = mp.index.map(p => p.slice(0, 10))

  const marginNames = [
    { col: 'gross_profit', name: 'Gross Margin' },
    { col: 'operating_income', name: 'Operating Margin' },
    { col: 'net_income', name: 'Net Margin' },
  ].filter(m => mp.columns.includes(m.col))

  const series = marginNames.map(m => {
    const ci = mp.columns.indexOf(m.col)
    return {
      name: m.name,
      data: mp.data.map((row, i) => {
        const v = row[ci]
        if (v == null || rev[i] == null || rev[i] === 0) return null
        return +(v / rev[i]! * 100).toFixed(2)
      }),
    }
  })

  return lineChart(periods, series, { ySuffix: '%', smooth: true })
})

const marginsEmptyMessage = computed(() => {
  const mp = props.data.margins_pivot
  if (!mp || marginsChart.value) return null

  const revCI = mp.columns.indexOf('revenue')
  if (revCI < 0) {
    return 'Revenue is unavailable for the selected period.'
  }

  const availableMetrics = ['gross_profit', 'operating_income', 'net_income']
    .filter(metric => mp.columns.includes(metric))
  if (!availableMetrics.length) {
    return 'Margin inputs are unavailable for the selected period.'
  }

  return 'Margin data is too sparse for the selected period.'
})

// Earnings quality: Net Income vs Operating Cash Flow (index=periods, columns=metrics)
const earningsChart = computed(() => {
  const eq = props.data.earnings_quality
  if (!eq || !eq.columns.length) return null

  const niCI = eq.columns.indexOf('net_income')
  const ocfCI = eq.columns.indexOf('operating_cash_flow')
  if (niCI < 0 || ocfCI < 0) return null

  const periods = eq.index.map(p => p.slice(0, 10))
  return barChart(
    periods,
    [
      { name: 'Net Income', data: eq.data.map(row => row[niCI]) },
      { name: 'Operating Cash Flow', data: eq.data.map(row => row[ocfCI]) },
    ],
    { yPrefix: '$' },
  )
})
</script>

<template>
  <div class="space-y-6">
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <Card v-if="growthChart">
        <CardHeader class="pb-2">
          <CardTitle class="text-base">Year-over-Year Growth</CardTitle>
        </CardHeader>
        <CardContent>
          <EChart :option="growthChart" autoresize class="h-72" />
        </CardContent>
      </Card>
      <Card v-if="data.margins_pivot && data.margins_pivot.columns.length > 0">
        <CardHeader class="pb-2">
          <CardTitle class="text-base">Margin Trends</CardTitle>
        </CardHeader>
        <CardContent>
          <EChart v-if="marginsChart" :option="marginsChart" autoresize class="h-72" />
          <div
            v-else
            class="h-72 flex items-center justify-center text-center text-sm text-muted-foreground"
          >
            {{ marginsEmptyMessage }}
          </div>
        </CardContent>
      </Card>
    </div>
    <Card v-if="earningsChart">
      <CardHeader class="pb-2">
        <CardTitle class="text-base">Earnings Quality — Net Income vs Operating Cash Flow</CardTitle>
      </CardHeader>
      <CardContent>
        <EChart :option="earningsChart" autoresize class="h-72" />
      </CardContent>
    </Card>
  </div>
</template>
