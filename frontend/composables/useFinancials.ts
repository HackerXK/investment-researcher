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

  async function fetchTab(tab: string) {
    if (!ticker.value) return
    loading.value = true
    try {
      switch (tab) {
        case 'income':
          income.value = await getFinancials(ticker.value, 'income', periodType.value)
          break
        case 'balance':
          balance.value = await getFinancials(ticker.value, 'balance', periodType.value)
          break
        case 'cashflow':
          cashflow.value = await getFinancials(ticker.value, 'cashflow', periodType.value)
          break
        case 'growth':
          growth.value = await getFinancials(ticker.value, 'growth', periodType.value)
          break
        case 'kpi':
          kpi.value = await getFinancials(ticker.value, 'kpi', periodType.value)
          break
        case 'ratios':
          ratios.value = await getRatios(ticker.value, periodType.value)
          break
        case 'health':
          health.value = await getHealth(ticker.value, periodType.value)
          break
        case 'quarterly':
          quarterly.value = await getQuarterly(ticker.value)
          break
        case 'filings':
          filings.value = await getFilings(ticker.value)
          break
      }
    } catch (e) {
      console.error(`Failed to fetch ${tab}:`, e)
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
