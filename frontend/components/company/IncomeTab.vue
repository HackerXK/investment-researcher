<script setup lang="ts">
import { computed } from 'vue'
import { Card, CardContent, CardHeader, CardTitle } from '~/components/ui/card'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '~/components/ui/table'
import type { FinancialsResponse } from '~/lib/api'
import { barChart, lineChart } from '~/lib/charts'
import { fmtMillions, deltaColor } from '~/lib/formatters'

const props = defineProps<{ data: FinancialsResponse; ticker: string }>()

// pivot shape: index=periods, columns=metrics, data[period_row][metric_col]
const pivot = computed(() => props.data.pivot)
const periods = computed(() => pivot.value?.index.map(p => p.slice(0, 10)) || [])
const metrics = computed(() => pivot.value?.columns || [])

function colData(metric: string): (number | null)[] {
  const p = pivot.value
  if (!p) return []
  const ci = p.columns.indexOf(metric)
  if (ci < 0) return []
  return p.data.map(row => row[ci])
}

const revenueChart = computed(() => {
  const p = pivot.value
  if (!p) return null
  const rev = colData('revenue')
  if (!rev.length) return null
  const series = [{ name: 'Revenue', data: rev }]
  const ni = colData('net_income')
  if (ni.length) series.push({ name: 'Net Income', data: ni })
  return barChart(periods.value, series, { yPrefix: '$' })
})

const marginChart = computed(() => {
  const p = pivot.value
  if (!p) return null
  const rev = colData('revenue')
  if (!rev.length) return null

  function marginSeries(name: string, metric: string) {
    const d = colData(metric)
    return {
      name,
      data: d.map((v, i) => {
        if (v == null || rev[i] == null || rev[i] === 0) return null
        return +(v / rev[i]! * 100).toFixed(2)
      }),
    }
  }

  const series = []
  if (metrics.value.includes('gross_profit')) series.push(marginSeries('Gross Margin', 'gross_profit'))
  if (metrics.value.includes('operating_income')) series.push(marginSeries('Operating Margin', 'operating_income'))
  if (metrics.value.includes('net_income')) series.push(marginSeries('Net Margin', 'net_income'))
  if (!series.length) return null

  return lineChart(periods.value, series, { ySuffix: '%' })
})

const marginEmptyMessage = computed(() => {
  if (!pivot.value || marginChart.value) return null

  const rev = colData('revenue')
  if (!rev.length) {
    return 'Revenue is unavailable for the selected period.'
  }

  const marginMetrics = ['gross_profit', 'operating_income', 'net_income']
  const availableMetrics = marginMetrics.filter(metric => metrics.value.includes(metric))
  if (!availableMetrics.length) {
    return 'Margin inputs are unavailable for the selected period.'
  }

  return 'Margin data is too sparse for the selected period.'
})
</script>

<template>
  <div class="space-y-6">
    <!-- Charts row -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <Card v-if="revenueChart">
        <CardHeader class="pb-2">
          <CardTitle class="text-base">Revenue & Net Income</CardTitle>
        </CardHeader>
        <CardContent>
          <EChart :option="revenueChart" autoresize class="h-72" />
        </CardContent>
      </Card>
      <Card v-if="pivot && pivot.columns.length > 0">
        <CardHeader class="pb-2">
          <CardTitle class="text-base">Margin Trends</CardTitle>
        </CardHeader>
        <CardContent>
          <EChart v-if="marginChart" :option="marginChart" autoresize class="h-72" />
          <div
            v-else
            class="h-72 flex items-center justify-center text-center text-sm text-muted-foreground"
          >
            {{ marginEmptyMessage }}
          </div>
        </CardContent>
      </Card>
    </div>

    <!-- Data table: metrics as rows, periods as columns -->
    <Card v-if="pivot && pivot.columns.length > 0">
      <CardHeader class="pb-2">
        <CardTitle class="text-base">Income Statement ($ millions)</CardTitle>
      </CardHeader>
      <CardContent class="overflow-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead class="sticky left-0 bg-card min-w-[180px]">Metric</TableHead>
              <TableHead
                v-for="p in periods"
                :key="p"
                class="text-right min-w-[100px]"
              >
                {{ p }}
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="(metric, colIdx) in metrics" :key="metric">
              <TableCell class="sticky left-0 bg-card font-medium text-sm capitalize">
                {{ metric.replace(/_/g, ' ') }}
              </TableCell>
              <TableCell
                v-for="(_, rowIdx) in periods"
                :key="rowIdx"
                class="text-right text-sm tabular-nums"
                :class="deltaColor(pivot.data[rowIdx][colIdx])"
              >
                {{ fmtMillions(pivot.data[rowIdx][colIdx]) }}
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  </div>
</template>
