<script setup lang="ts">
import { computed } from 'vue'
import { Card, CardContent, CardHeader, CardTitle } from '~/components/ui/card'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '~/components/ui/table'
import type { FinancialsResponse } from '~/lib/api'
import { barChart } from '~/lib/charts'
import { buildStatementTableView } from '~/lib/financialTables'
import { fmtMillions } from '~/lib/formatters'

const props = defineProps<{ data: FinancialsResponse; ticker: string }>()

const pivot = computed(() => props.data.pivot)
const periods = computed(() => pivot.value?.index.map(p => p.slice(0, 10)) || [])
const metrics = computed(() => pivot.value?.columns || [])
const table = computed(() => buildStatementTableView(pivot.value, props.data.ttm))

function colData(metric: string): (number | null)[] {
  const p = pivot.value
  if (!p) return []
  const ci = p.columns.indexOf(metric)
  if (ci < 0) return []
  return p.data.map(row => row[ci])
}

const assetsLiabChart = computed(() => {
  const p = pivot.value
  if (!p) return null
  const series = []
  if (metrics.value.includes('total_assets')) series.push({ name: 'Total Assets', data: colData('total_assets') })
  if (metrics.value.includes('total_liabilities')) series.push({ name: 'Total Liabilities', data: colData('total_liabilities') })
  if (metrics.value.includes('stockholders_equity')) series.push({ name: 'Equity', data: colData('stockholders_equity') })
  if (!series.length) return null
  return barChart(periods.value, series, { yPrefix: '$' })
})

const debtChart = computed(() => {
  const p = pivot.value
  if (!p) return null
  const series = []
  if (metrics.value.includes('short_term_debt')) series.push({ name: 'Short-term Debt', data: colData('short_term_debt') })
  if (metrics.value.includes('long_term_debt')) series.push({ name: 'Long-term Debt', data: colData('long_term_debt') })
  if (metrics.value.includes('cash')) series.push({ name: 'Cash', data: colData('cash') })
  if (!series.length) return null
  return barChart(periods.value, series, { yPrefix: '$' })
})
</script>

<template>
  <div class="space-y-6">
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <Card v-if="assetsLiabChart">
        <CardHeader class="pb-2">
          <CardTitle class="text-base">Assets, Liabilities & Equity</CardTitle>
        </CardHeader>
        <CardContent>
          <EChart :option="assetsLiabChart" autoresize class="h-72" />
        </CardContent>
      </Card>
      <Card v-if="debtChart">
        <CardHeader class="pb-2">
          <CardTitle class="text-base">Debt vs Cash</CardTitle>
        </CardHeader>
        <CardContent>
          <EChart :option="debtChart" autoresize class="h-72" />
        </CardContent>
      </Card>
    </div>

    <Card v-if="table.metrics.length > 0">
      <CardHeader class="pb-2">
        <CardTitle class="text-base">Balance Sheet ($ millions)</CardTitle>
      </CardHeader>
      <CardContent class="overflow-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead class="sticky left-0 bg-card min-w-[180px]">Metric</TableHead>
              <TableHead v-for="p in table.periods" :key="p" class="text-right min-w-[100px]">{{ p }}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="(metric, rowIdx) in table.metrics" :key="metric">
              <TableCell class="sticky left-0 bg-card font-medium text-sm capitalize">
                {{ metric.replace(/_/g, ' ') }}
              </TableCell>
              <TableCell
                v-for="(value, colIdx) in table.values[rowIdx]"
                :key="colIdx"
                class="text-right text-sm tabular-nums"
              >
                {{ fmtMillions(value) }}
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  </div>
</template>
