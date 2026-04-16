/**
 * Number formatting utilities — ported from the Streamlit demo.
 */

export type MetricDisplayFormat = 'millions' | 'per_share' | 'count' | 'number'

export function fmtCurrency(val: number | null | undefined): string {
  if (val == null) return 'N/A'
  const abs = Math.abs(val)
  const sign = val < 0 ? '-' : ''
  if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(2)}T`
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(1)}M`
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(1)}K`
  return `${sign}$${abs.toFixed(2)}`
}

export function fmtCount(val: number | null | undefined): string {
  if (val == null) return 'N/A'
  const abs = Math.abs(val)
  if (abs >= 1e9) return `${(val / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `${(val / 1e6).toFixed(1)}M`
  if (abs >= 1e3) return `${(val / 1e3).toFixed(1)}K`
  return val.toFixed(0)
}

export function fmtPercent(val: number | null | undefined): string {
  if (val == null) return 'N/A'
  return `${(val * 100).toFixed(1)}%`
}

export function fmtRatio(val: number | null | undefined, fmt: string): string {
  if (val == null) return 'N/A'
  if (fmt === 'pct') return `${(val * 100).toFixed(2)}%`
  if (fmt === 'days') return `${val.toFixed(1)} days`
  if (fmt === 'dollar') return fmtCurrency(val)
  return `${val.toFixed(2)}x`
}

export function fmtMillions(val: number | null | undefined): string {
  if (val == null) return '—'
  const abs = Math.abs(val)
  const sign = val < 0 ? '-' : ''
  return `${sign}${(abs / 1e6).toLocaleString('en-US', { maximumFractionDigits: 0 })}`
}

export function fmtPerShare(val: number | null | undefined): string {
  if (val == null) return '—'
  const abs = Math.abs(val)
  const sign = val < 0 ? '-' : ''
  return `${sign}$${abs.toFixed(2)}`
}

export function fmtNumber(val: number | null | undefined): string {
  if (val == null) return '—'
  return val.toLocaleString('en-US', { maximumFractionDigits: 2 })
}

export function fmtMetricValue(
  val: number | null | undefined,
  format: MetricDisplayFormat = 'millions',
): string {
  if (format === 'per_share') return fmtPerShare(val)
  if (format === 'count') return fmtCount(val)
  if (format === 'number') return fmtNumber(val)
  return fmtMillions(val)
}

export function deltaColor(val: number | null | undefined): string {
  if (val == null) return 'text-muted-foreground'
  return val >= 0 ? 'text-gain' : 'text-loss'
}
