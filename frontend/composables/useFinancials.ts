/**
 * Financial data composable — fetches tab-specific data.
 */
import { ref, type Ref, watch } from 'vue'
import {
  getFinancials,
  getRatios,
  getHealth,
  getQuarterly,
  getFilings,
  type FinancialsResponse,
  type RatiosResponse,
  type HealthResponse,
  type QuarterlyResponse,
  type Filing,
} from '~/lib/api'

const financialTabs = [
  'income',
  'balance',
  'cashflow',
  'growth',
  'kpi',
  'ratios',
  'health',
  'quarterly',
  'filings',
] as const

type StatementTab = 'income' | 'balance' | 'cashflow' | 'growth' | 'kpi'
type FinancialTab = (typeof financialTabs)[number]

function isFinancialTab(tab: string): tab is FinancialTab {
  return financialTabs.includes(tab as FinancialTab)
}

export function useFinancials(ticker: Ref<string>, periodType: Ref<string>) {
  // Income
  const income = ref<FinancialsResponse | null>(null)
  const balance = ref<FinancialsResponse | null>(null)
  const cashflow = ref<FinancialsResponse | null>(null)
  const growth = ref<FinancialsResponse | null>(null)
  const kpi = ref<FinancialsResponse | null>(null)
  const ratios = ref<RatiosResponse | null>(null)
  const health = ref<HealthResponse | null>(null)
  const quarterly = ref<QuarterlyResponse | null>(null)
  const filings = ref<Filing[]>([])
  const loading = ref(false)

  async function fetchStatement(
    target: typeof income,
    tab: StatementTab,
  ) {
    target.value = await getFinancials(ticker.value, tab, periodType.value)
  }

  const tabFetchers: Record<FinancialTab, () => Promise<void>> = {
    income: () => fetchStatement(income, 'income'),
    balance: () => fetchStatement(balance, 'balance'),
    cashflow: () => fetchStatement(cashflow, 'cashflow'),
    growth: () => fetchStatement(growth, 'growth'),
    kpi: () => fetchStatement(kpi, 'kpi'),
    ratios: async () => {
      ratios.value = await getRatios(ticker.value, periodType.value)
    },
    health: async () => {
      health.value = await getHealth(ticker.value, periodType.value)
    },
    quarterly: async () => {
      quarterly.value = await getQuarterly(ticker.value)
    },
    filings: async () => {
      filings.value = await getFilings(ticker.value)
    },
  }

  async function fetchTab(tab: string) {
    if (!ticker.value || !isFinancialTab(tab)) return

    loading.value = true
    try {
      await tabFetchers[tab]()
    } catch (error) {
      console.error(`Failed to fetch ${tab}:`, error)
    } finally {
      loading.value = false
    }
  }

  // Refetch KPI when ticker or period changes
  watch([ticker, periodType], () => {
    if (ticker.value) fetchTab('kpi')
  }, { immediate: true })

  return {
    income, balance, cashflow, growth, kpi,
    ratios, health, quarterly, filings,
    loading, fetchTab,
  }
}
