<script setup lang="ts">
import { computed } from 'vue'
import { Card, CardContent, CardHeader, CardTitle } from '~/components/ui/card'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '~/components/ui/table'
import type { QuarterlyResponse } from '~/lib/api'
import { barChart } from '~/lib/charts'
import { deltaColor, fmtMetricValue } from '~/lib/formatters'

const props = defineProps<{ data: QuarterlyResponse; ticker: string }>()

const qd = computed(() => props.data.quarterly)
const metricDisplayFormats = computed(() => props.data.metric_display_formats || {})
const periods = computed(() => qd.value?.columns || [])
const metrics = computed(() => qd.value?.index || [])

function rowData(metric: string): (number | null)[] {
  const q = qd.value
  if (!q) return []
  const ri = q.index.indexOf(metric)
  if (ri < 0) return []
  return q.data[ri] || []
}

function fmtTableValue(metric: string, val: number | null) {
  return fmtMetricValue(val, metricDisplayFormats.value[metric] || 'millions')
}

function formatPeriodLabel(period: string) {
  return period === 'TTM' ? 'TTM' : period.replace(/-/g, ' ')
}

const revenueChart = computed(() => {
  const q = qd.value
  if (!q) return null
  const rev = rowData('revenue')
  if (!rev.length) return null
  const series = [{ name: 'Revenue', data: rev }]
  const ni = rowData('net_income')
  if (ni.length) series.push({ name: 'Net Income', data: ni })
  return barChart(periods.value, series, { yPrefix: '$' })
})

const epsChart = computed(() => {
  const q = qd.value
  if (!q) return null
  const eps = rowData('eps_diluted')
  if (!eps.length) return null
  return barChart(periods.value, [{ name: 'EPS Diluted', data: eps }], { yPrefix: '$' })
})
</script>

<template>
  <div class="space-y-6">
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <Card v-if="revenueChart">
        <CardHeader class="pb-2">
          <CardTitle class="text-base">Quarterly Revenue & Net Income</CardTitle>
        </CardHeader>
        <CardContent>
          <EChart :option="revenueChart" autoresize class="h-72" />
        </CardContent>
      </Card>
      <Card v-if="epsChart">
        <CardHeader class="pb-2">
          <CardTitle class="text-base">Quarterly EPS</CardTitle>
        </CardHeader>
        <CardContent>
          <EChart :option="epsChart" autoresize class="h-72" />
        </CardContent>
      </Card>
    </div>

    <Card v-if="qd && qd.columns.length > 0">
      <CardHeader class="pb-2">
        <CardTitle class="text-base">Quarterly Detail</CardTitle>
      </CardHeader>
      <CardContent class="overflow-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead class="sticky left-0 bg-card min-w-[180px]">Metric</TableHead>
              <TableHead v-for="p in periods" :key="p" class="text-right min-w-[100px]">{{ formatPeriodLabel(p) }}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="(metric, rowIdx) in metrics" :key="metric">
              <TableCell class="sticky left-0 bg-card font-medium text-sm capitalize">
                {{ metric.replace(/_/g, ' ') }}
              </TableCell>
              <TableCell
                v-for="(_, colIdx) in periods"
                :key="colIdx"
                class="text-right text-sm tabular-nums"
                :class="deltaColor(qd.data[rowIdx][colIdx])"
              >
                {{ fmtTableValue(metric, qd.data[rowIdx][colIdx]) }}
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  </div>
</template>
