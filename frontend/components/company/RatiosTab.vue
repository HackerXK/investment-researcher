<script setup lang="ts">
import { computed } from 'vue'
import { Card, CardContent, CardHeader, CardTitle } from '~/components/ui/card'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '~/components/ui/table'
import { Badge } from '~/components/ui/badge'
import type { RatiosResponse } from '~/lib/api'
import { lineChart } from '~/lib/charts'
import { fmtRatio } from '~/lib/formatters'

const props = defineProps<{ data: RatiosResponse; ticker: string }>()

const wide = computed(() => props.data.wide)
const categories = computed(() => props.data.categories || {})

// Build a chart for each category with > 1 period of data
// wide shape: index=periods, columns=ratio_names, data[period_row][ratio_col]
const categoryCharts = computed(() => {
  const w = wide.value
  if (!w || !w.columns.length) return []

  const periods = w.index.map(p => p.slice(0, 10))
  const result: { title: string; option: any; ratios: { name: string; latest: string; ttm: string }[] }[] = []

  for (const [catName, defs] of Object.entries(categories.value)) {
    const series: { name: string; data: (number | null)[] }[] = []
    const ratioSummary: { name: string; latest: string; ttm: string }[] = []

    for (const def of defs) {
      const colIdx = w.columns.indexOf(def.name)
      if (colIdx < 0) continue

      const needsPctScale = def.display_format === 'pct'
      const data = w.data.map(row => {
        const v = row[colIdx]
        if (v == null) return null
        return needsPctScale ? +(v * 100).toFixed(2) : +v.toFixed(3)
      })
      series.push({ name: def.name.replace(/_/g, ' '), data })

      ratioSummary.push({
        name: def.name.replace(/_/g, ' '),
        latest: fmtRatio(props.data.latest?.[def.name] ?? null, def.display_format),
        ttm: fmtRatio(props.data.ttm?.[def.name] ?? null, def.display_format),
      })
    }

    if (series.length === 0) continue

    const hasPctFormat = defs.some(d => d.display_format === 'pct')
    result.push({
      title: catName.replace(/_/g, ' '),
      option: lineChart(periods, series, { ySuffix: hasPctFormat ? '%' : '' }),
      ratios: ratioSummary,
    })
  }

  return result
})
</script>

<template>
  <div class="space-y-8">
    <div
      v-for="cat in categoryCharts"
      :key="cat.title"
    >
      <h3 class="text-sm font-semibold uppercase tracking-widest text-muted-foreground mb-4 capitalize">{{ cat.title }}</h3>
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <!-- Chart -->
        <Card class="lg:col-span-2">
          <CardContent class="pt-6">
            <EChart :option="cat.option" autoresize class="h-64" />
          </CardContent>
        </Card>
        <!-- Summary table -->
        <Card>
          <CardContent class="pt-6">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Ratio</TableHead>
                  <TableHead class="text-right">Latest</TableHead>
                  <TableHead class="text-right">TTM</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow v-for="r in cat.ratios" :key="r.name">
                  <TableCell class="text-sm capitalize">{{ r.name }}</TableCell>
                  <TableCell class="text-right text-sm tabular-nums font-medium">{{ r.latest }}</TableCell>
                  <TableCell class="text-right text-sm tabular-nums text-muted-foreground">{{ r.ttm }}</TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </div>

    <div v-if="categoryCharts.length === 0" class="text-center text-muted-foreground py-12">
      No ratio data available for {{ ticker }}.
    </div>
  </div>
</template>
