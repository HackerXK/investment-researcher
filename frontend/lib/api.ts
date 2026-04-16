/**
 * Typed API client for the FastAPI backend.
 */

import type { MetricDisplayFormat } from '~/lib/formatters'

const API_BASE = () => {
  if (import.meta.server) {
    return process.env.NUXT_PUBLIC_API_BASE || 'http://localhost:8080'
  }
  return ''  // Use proxy in browser
}

async function apiFetch<T = any>(path: string, opts?: RequestInit): Promise<T> {
  const base = API_BASE()
  const url = `${base}${path}`
  const res = await fetch(url, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      ...opts?.headers,
    },
  })
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${res.statusText}`)
  }
  return res.json()
}

// ── Company endpoints ─────────────────────────────────────────────

export interface CompanySearchResult {
  ticker: string
}

export interface CompanyProfile {
  ticker: string
  name?: string
  cik?: string
  sic?: string
  sic_description?: string
  state?: string
  fiscal_year_end?: string
  latest_metrics?: Record<string, number | null>
  last_period?: string
}

export function searchCompanies(q: string, limit = 20): Promise<CompanySearchResult[]> {
  return apiFetch(`/api/companies/search?q=${encodeURIComponent(q)}&limit=${limit}`)
}

export function getCompanyProfile(ticker: string): Promise<CompanyProfile> {
  return apiFetch(`/api/companies/${ticker}`)
}

export function getAllTickers(): Promise<string[]> {
  return apiFetch('/api/companies')
}

// ── Financials ────────────────────────────────────────────────────

export interface WideData {
  index: string[]
  columns: string[]
  data: (number | null)[][]
}

export interface FinancialsResponse {
  timeseries?: any[]
  pivot?: WideData
  growth?: any[]
  margins_pivot?: WideData
  earnings_quality?: WideData
  summary?: any[]
  ttm?: Record<string, number | null>
  metric_display_formats?: Record<string, MetricDisplayFormat>
}

export function getFinancials(
  ticker: string,
  tab: string,
  periodType = 'annual',
): Promise<FinancialsResponse> {
  return apiFetch(
    `/api/companies/${ticker}/financials?tab=${tab}&period_type=${periodType}`,
  )
}

export interface RatiosResponse {
  latest: Record<string, number | null>
  wide: WideData
  ttm: Record<string, number | null>
  categories: Record<string, { name: string; display_format: string }[]>
}

export function getRatios(ticker: string, periodType = 'annual'): Promise<RatiosResponse> {
  return apiFetch(`/api/companies/${ticker}/financials/ratios?period_type=${periodType}`)
}

export interface HealthResponse {
  ratios_latest: Record<string, number | null>
  ratios_ttm: Record<string, number | null>
  revenue_growth: any[]
}

export function getHealth(ticker: string, periodType = 'annual'): Promise<HealthResponse> {
  return apiFetch(`/api/companies/${ticker}/financials/health?period_type=${periodType}`)
}

export interface QuarterlyResponse {
  quarterly: WideData
  metric_display_formats?: Record<string, MetricDisplayFormat>
}

export function getQuarterly(ticker: string, n = 10): Promise<QuarterlyResponse> {
  return apiFetch(`/api/companies/${ticker}/financials/quarterly?n_quarters=${n}`)
}

// ── Filings ───────────────────────────────────────────────────────

export interface Filing {
  accession_number: string
  form_type: string
  filing_date: string
  primary_document?: string
  description?: string
}

export function getFilings(
  ticker: string,
  formType?: string,
  limit = 25,
): Promise<Filing[]> {
  let url = `/api/companies/${ticker}/filings?limit=${limit}`
  if (formType) url += `&form_type=${formType}`
  return apiFetch(url)
}

export function getFilingText(
  ticker: string,
  accession: string,
): Promise<{ accession_number: string; text: string }> {
  return apiFetch(`/api/companies/${ticker}/filings/${accession}`)
}
