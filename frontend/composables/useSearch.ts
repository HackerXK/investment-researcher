/**
 * Debounced company search composable.
 */
import { ref, watch } from 'vue'
import { searchCompanies, type CompanySearchResult } from '~/lib/api'

export function useSearch() {
  const query = ref('')
  const results = ref<CompanySearchResult[]>([])
  const loading = ref(false)
  let timeout: ReturnType<typeof setTimeout> | null = null

  watch(query, (q) => {
    if (timeout) clearTimeout(timeout)
    if (!q || q.length < 1) {
      results.value = []
      return
    }
    loading.value = true
    timeout = setTimeout(async () => {
      try {
        results.value = await searchCompanies(q, 10)
      } catch {
        results.value = []
      } finally {
        loading.value = false
      }
    }, 200)
  })

  return { query, results, loading }
}
