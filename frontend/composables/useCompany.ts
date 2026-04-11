/**
 * Company profile composable — fetches profile once per ticker.
 */
import { ref, watch, type Ref } from 'vue'
import { getCompanyProfile, type CompanyProfile } from '~/lib/api'

export function useCompany(ticker: Ref<string>) {
  const company = ref<CompanyProfile | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchProfile() {
    if (!ticker.value) return
    loading.value = true
    error.value = null
    try {
      company.value = await getCompanyProfile(ticker.value)
    } catch (e: any) {
      error.value = e.message || 'Failed to load company'
    } finally {
      loading.value = false
    }
  }

  watch(ticker, fetchProfile, { immediate: true })

  return { company, loading, error, refresh: fetchProfile }
}
