<script setup lang="ts">
import { computed } from 'vue'
import { Card, CardContent, CardHeader, CardTitle } from '~/components/ui/card'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '~/components/ui/table'
import type { FinancialsResponse } from '~/lib/api'
import { barChart, lineChart } from '~/lib/charts'
import { fmtMillions, deltaColor } from '~/lib/formatters'

const props = defineProps<{ data: FinancialsResponse; ticker: string }>()

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

const cfChart = computed(() => {
  const p = pivot.value
  if (!p) return null
  const series = []
  if (metrics.value.includes('operating_cash_flow')) series.push({ name: 'Operating', data: colData('operating_cash_flow') })
  if (metrics.value.includes('investing_cash_flow')) series.push({ name: 'Investing', data: colData('investing_cash_flow') })
  if (metrics.value.includes('financing_cash_flow')) series.push({ name: 'Financing', data: colData('financing_cash_flow') })
  if (!series.length) return null
  return barChart(periods.value, series, { yPrefix: '$' })
})

const fcfChart = computed(() => {
  const p = pivot.value
  if (!p) return null
  const op = colData('operating_cash_flow')
  const cap = colData('capex')
  if (!op.length || !cap.length) return null
  const fcf = op.map((v, i) => {
    const c = cap[i]
    if (v == null || c == null) return null
    return v + c // capex is already negative
  })
  return lineChart(
    periods.value,
    [
      { name: 'Operating CF', data: op },
      { name: 'Free Cash Flow', data: fcf },
    ],
  )
})
</script>

<template>
  <div class="space-y-6">
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <Card v-if="cfChart">
        <CardHeader class="pb-2">
          <CardTitle class="text-base">Cash Flow Breakdown</CardTitle>
        </CardHeader>
        <CardContent>
          <EChart :option="cfChart" autoresize class="h-72" />
        </CardContent>
      </Card>
      <Card v-if="fcfChart">
        <CardHeader class="pb-2">
          <CardTitle class="text-base">Operating CF vs Free Cash Flow</CardTitle>
        </CardHeader>
        <CardContent>
          <EChart :option="fcfChart" autoresize class="h-72" />
        </CardContent>
      </Card>
    </div>

    <Card v-if="pivot && pivot.columns.length > 0">
      <CardHeader class="pb-2">
        <CardTitle class="text-base">Cash Flow Statement ($ millions)</CardTitle>
      </CardHeader>
      <CardContent class="overflow-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead class="sticky left-0 bg-card min-w-[180px]">Metric</TableHead>
              <TableHead v-for="p in periods" :key="p" class="text-right min-w-[100px]">{{ p }}</TableHead>
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
