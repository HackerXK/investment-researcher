<script setup lang="ts">
import { ref } from 'vue'
import { FileText, ExternalLink, ChevronDown } from 'lucide-vue-next'
import { Card, CardContent, CardHeader, CardTitle } from '~/components/ui/card'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Skeleton } from '~/components/ui/skeleton'
import type { Filing } from '~/lib/api'
import { getFilingText } from '~/lib/api'

const props = defineProps<{ filings: Filing[]; ticker: string }>()
const emit = defineEmits<{ refresh: [] }>()

const expandedAccession = ref<string | null>(null)
const filingText = ref<string>('')
const loadingText = ref(false)

async function toggle(accession: string) {
  if (expandedAccession.value === accession) {
    expandedAccession.value = null
    filingText.value = ''
    return
  }
  expandedAccession.value = accession
  loadingText.value = true
  try {
    const res = await getFilingText(props.ticker, accession)
    filingText.value = res.text
  } catch {
    filingText.value = 'Failed to load filing text.'
  } finally {
    loadingText.value = false
  }
}

const formColors: Record<string, string> = {
  '10-K': 'bg-sky-100 text-sky-800',
  '10-Q': 'bg-violet-100 text-violet-800',
  '8-K': 'bg-amber-100 text-amber-800',
  'DEF 14A': 'bg-emerald-100 text-emerald-800',
}

function badgeClass(formType: string): string {
  return formColors[formType] || 'bg-muted text-muted-foreground'
}
</script>

<template>
  <div>
    <div v-if="!filings.length" class="text-center text-muted-foreground py-12">
      <Button variant="outline" @click="emit('refresh')">Load Filings</Button>
    </div>

    <div v-else class="space-y-2">
      <Card
        v-for="f in filings"
        :key="f.accession_number"
        class="overflow-hidden transition-shadow hover:shadow-md"
      >
        <button
          class="flex w-full items-center gap-4 p-4 text-left"
          @click="toggle(f.accession_number)"
        >
          <FileText class="h-5 w-5 text-muted-foreground shrink-0" />
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 mb-0.5">
              <span :class="['inline-flex rounded px-1.5 py-0.5 text-[10px] font-semibold', badgeClass(f.form_type)]">
                {{ f.form_type }}
              </span>
              <span class="text-sm font-medium truncate">{{ f.description || f.accession_number }}</span>
            </div>
            <div class="text-xs text-muted-foreground">
              Filed {{ f.filing_date }} · {{ f.accession_number }}
            </div>
          </div>
          <ChevronDown
            class="h-4 w-4 text-muted-foreground shrink-0 transition-transform"
            :class="expandedAccession === f.accession_number ? 'rotate-180' : ''"
          />
        </button>

        <!-- Expanded filing text -->
        <div
          v-if="expandedAccession === f.accession_number"
          class="border-t bg-muted/30"
        >
          <div v-if="loadingText" class="p-6 space-y-3">
            <Skeleton class="h-4 w-full" />
            <Skeleton class="h-4 w-5/6" />
            <Skeleton class="h-4 w-4/6" />
          </div>
          <div v-else class="p-6 max-h-[600px] overflow-auto">
            <pre class="text-xs leading-relaxed whitespace-pre-wrap font-mono text-muted-foreground">{{ filingText }}</pre>
          </div>
        </div>
      </Card>
    </div>
  </div>
</template>
