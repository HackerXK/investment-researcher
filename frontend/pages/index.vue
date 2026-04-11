<script setup lang="ts">
import { Search, TrendingUp, ArrowRight, Building2 } from 'lucide-vue-next'
import { Input } from '~/components/ui/input'
import { useSearch } from '~/composables/useSearch'

const { query, results, searching } = useSearch()

function go(ticker: string) {
  navigateTo(`/company/${ticker}`)
}
</script>

<template>
  <div class="flex flex-col items-center pt-20 pb-16 w-full">
    <!-- Hero -->
    <div class="flex flex-col items-center text-center max-w-2xl mb-12">
      <div class="inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs text-muted-foreground mb-6">
        <TrendingUp class="h-3 w-3" />
        SEC XBRL Financial Intelligence
      </div>
      <h1 class="text-4xl sm:text-5xl font-bold tracking-tight mb-4">
        Research any public company
      </h1>
      <p class="text-lg text-muted-foreground leading-relaxed">
        Financial statements, ratios, growth metrics, and AI-powered analysis — all derived from SEC XBRL filings.
      </p>
    </div>

    <!-- Search -->
    <div class="relative w-full max-w-lg mb-16">
      <div class="relative">
        <Search class="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
        <Input
          v-model="query"
          placeholder="Search by ticker (e.g. AAPL, NVDA, UNH)"
          class="pl-10 h-12 text-base rounded-xl shadow-sm border-muted"
        />
        <div
          v-if="searching"
          class="absolute right-3.5 top-1/2 -translate-y-1/2 h-4 w-4 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent"
        />
      </div>

      <!-- Results dropdown -->
      <div
        v-if="results.length > 0"
        class="absolute top-full mt-2 w-full rounded-xl border bg-popover shadow-lg overflow-hidden z-50"
      >
        <button
          v-for="r in results"
          :key="r.ticker"
          class="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-accent group"
          @click="go(r.ticker)"
        >
          <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted font-semibold text-xs">
            {{ r.ticker.slice(0, 2) }}
          </div>
          <div class="flex-1 min-w-0">
            <div class="font-medium text-sm truncate">{{ r.ticker }}</div>
            <div class="text-xs text-muted-foreground truncate">{{ r.name || 'SEC Registrant' }}</div>
          </div>
          <ArrowRight class="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
        </button>
      </div>
    </div>

    <!-- Quick access -->
    <div class="w-full max-w-3xl">
      <h2 class="text-xs font-medium text-muted-foreground uppercase tracking-widest mb-4">Popular companies</h2>
      <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
        <button
          v-for="t in ['AAPL', 'NVDA', 'MSFT', 'GOOG', 'AMZN', 'UNH', 'WMT', 'XOM', 'JPM', 'META']"
          :key="t"
          class="flex items-center gap-2.5 rounded-lg border px-4 py-3 text-sm transition-colors hover:bg-accent hover:border-accent-foreground/20 group"
          @click="go(t)"
        >
          <Building2 class="h-3.5 w-3.5 text-muted-foreground group-hover:text-foreground transition-colors" />
          <span class="font-medium">{{ t }}</span>
        </button>
      </div>
    </div>
  </div>
</template>
