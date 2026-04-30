import type { WideData } from '~/lib/api'

export interface FinancialTableView {
  periods: string[]
  metrics: string[]
  values: (number | null)[][]
}

function periodSortValue(period: string): number {
  if (period === 'TTM') return Number.POSITIVE_INFINITY

  if (/^\d{4}-\d{2}-\d{2}$/.test(period)) {
    return Date.parse(period)
  }

  const fiscalMatch = period.match(/^(FY|Q([1-4]))-(\d{4})$/)
  if (fiscalMatch) {
    const year = Number(fiscalMatch[3])
    const quarter = fiscalMatch[1] === 'FY' ? 5 : Number(fiscalMatch[2])
    return year * 10 + quarter
  }

  const parsed = Date.parse(period)
  return Number.isNaN(parsed) ? Number.NEGATIVE_INFINITY : parsed
}

function orderPeriodsForTable(periods: string[]) {
  return periods
    .map((period, index) => ({ period, index }))
    .sort((left, right) => periodSortValue(right.period) - periodSortValue(left.period))
}

function normalizePeriod(period: string) {
  return period === 'TTM' ? period : period.slice(0, 10)
}


export function extractMetricColumn(
  pivot: WideData | null | undefined,
  metric: string,
): (number | null)[] {
  if (!pivot) {
    return []
  }

  const columnIndex = pivot.columns.indexOf(metric)
  if (columnIndex < 0) {
    return []
  }

  return pivot.data.map(row => row[columnIndex] ?? null)
}

export function buildStatementTableView(
  pivot?: WideData | null,
  ttm?: Record<string, number | null>,
): FinancialTableView {
  if (!pivot?.columns?.length || !pivot.index.length) {
    return { periods: [], metrics: [], values: [] }
  }

  const orderedPeriods = orderPeriodsForTable(pivot.index.map(normalizePeriod))
  const includeTtm = ttm !== undefined
  const periods = includeTtm
    ? ['TTM', ...orderedPeriods.map(({ period }) => period)]
    : orderedPeriods.map(({ period }) => period)

  const values = pivot.columns.map((metric, columnIndex) => {
    const orderedValues = orderedPeriods.map(
      ({ index }) => pivot.data[index]?.[columnIndex] ?? null,
    )
    return includeTtm ? [ttm?.[metric] ?? null, ...orderedValues] : orderedValues
  })

  return {
    periods,
    metrics: [...pivot.columns],
    values,
  }
}

export function buildMetricRowTableView(wide?: WideData | null): FinancialTableView {
  if (!wide?.columns?.length || !wide.index.length) {
    return { periods: [], metrics: [], values: [] }
  }

  const orderedPeriods = orderPeriodsForTable(wide.columns.map(normalizePeriod))

  return {
    periods: orderedPeriods.map(({ period }) => period),
    metrics: [...wide.index],
    values: wide.data.map((row) => orderedPeriods.map(({ index }) => row?.[index] ?? null)),
  }
}
