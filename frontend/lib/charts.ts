/**
 * ECharts option builders for financial charts.
 */

import type { EChartsOption } from 'echarts'

const COLORS = {
  sky: '#38bdf8',
  emerald: '#10b981',
  violet: '#a78bfa',
  amber: '#f59e0b',
  rose: '#f43f5e',
  teal: '#2dd4bf',
  slate: '#64748b',
}

const COLOR_SEQ = [
  COLORS.sky, COLORS.emerald, COLORS.violet,
  COLORS.amber, COLORS.rose, COLORS.teal,
]

function baseOptions(overrides: Partial<EChartsOption> = {}): EChartsOption {
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    ...overrides,
  }
}

export function barChart(
  categories: string[],
  seriesList: { name: string; data: (number | null)[] }[],
  opts: { yPrefix?: string; colors?: string[] } = {},
): EChartsOption {
  const colors = opts.colors || COLOR_SEQ
  return {
    ...baseOptions(),
    color: colors,
    xAxis: { type: 'category', data: categories },
    yAxis: {
      type: 'value',
      axisLabel: { formatter: (v: number) => `${opts.yPrefix || ''}${abbreviate(v)}` },
    },
    series: seriesList.map((s, i) => ({
      name: s.name,
      type: 'bar',
      data: s.data,
      itemStyle: { borderRadius: [3, 3, 0, 0] },
    })),
    legend: { show: seriesList.length > 1 },
  }
}

export function lineChart(
  categories: string[],
  seriesList: { name: string; data: (number | null)[] }[],
  opts: { ySuffix?: string; colors?: string[]; smooth?: boolean } = {},
): EChartsOption {
  const colors = opts.colors || COLOR_SEQ
  return {
    ...baseOptions(),
    color: colors,
    xAxis: { type: 'category', data: categories },
    yAxis: {
      type: 'value',
      axisLabel: { formatter: (v: number) => `${abbreviate(v)}${opts.ySuffix || ''}` },
    },
    series: seriesList.map((s) => ({
      name: s.name,
      type: 'line',
      data: s.data,
      smooth: opts.smooth ?? true,
      symbol: 'circle',
      symbolSize: 6,
    })),
    legend: { show: seriesList.length > 1 },
  }
}

export function pieChart(
  data: { name: string; value: number }[],
  opts: { colors?: string[] } = {},
): EChartsOption {
  return {
    ...baseOptions(),
    color: opts.colors || COLOR_SEQ,
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    series: [
      {
        type: 'pie',
        radius: ['45%', '70%'],
        data,
        label: { show: true, formatter: '{b}\n{d}%', fontSize: 11 },
        emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0,0,0,0.5)' } },
      },
    ],
  }
}

export function radarChart(
  categories: string[],
  values: number[],
  opts: { name?: string; maxVal?: number } = {},
): EChartsOption {
  const max = opts.maxVal ?? 100
  return {
    ...baseOptions(),
    color: [COLORS.sky],
    radar: {
      indicator: categories.map((c) => ({ name: c, max })),
      shape: 'polygon',
    },
    series: [
      {
        type: 'radar',
        data: [{ value: values, name: opts.name || '' }],
        areaStyle: { opacity: 0.15 },
        lineStyle: { width: 2 },
        symbol: 'circle',
        symbolSize: 6,
      },
    ],
  }
}

function abbreviate(val: number): string {
  const abs = Math.abs(val)
  if (abs >= 1e12) return `${(val / 1e12).toFixed(1)}T`
  if (abs >= 1e9) return `${(val / 1e9).toFixed(1)}B`
  if (abs >= 1e6) return `${(val / 1e6).toFixed(1)}M`
  if (abs >= 1e3) return `${(val / 1e3).toFixed(1)}K`
  return val.toFixed(0)
}

export { COLORS, COLOR_SEQ }
