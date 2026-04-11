<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { MessageSquare, ArrowLeft, ExternalLink } from 'lucide-vue-next'
import { Button } from '~/components/ui/button'
import { Badge } from '~/components/ui/badge'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '~/components/ui/tabs'
import { Skeleton } from '~/components/ui/skeleton'
import { Sheet, SheetTrigger, SheetContent, SheetHeader, SheetTitle } from '~/components/ui/sheet'
import { Select } from '~/components/ui/select'
import { useCompany } from '~/composables/useCompany'
import { useFinancials } from '~/composables/useFinancials'
import { fmtCurrency, fmtPercent } from '~/lib/formatters'

const route = useRoute()
const ticker = computed(() => (route.params.ticker as string).toUpperCase())
const tickerRef = ref(ticker.value)
watch(ticker, (v) => { tickerRef.value = v })

const { company, loading: profileLoading } = useCompany(tickerRef)

const periodType = ref('annual')
const periodOptions = [
  { value: 'annual', label: 'Annual' },
  { value: 'quarterly', label: 'Quarterly' },
]

const activeTab = ref('income')
const { income, balance, cashflow, growth, kpi, ratios, health, quarterly, filings, loading: tabLoading, fetchTab } = useFinancials(tickerRef, periodType)

// Fetch initial tabs
watch(activeTab, (tab) => fetchTab(tab), { immediate: true })
watch(periodType, () => fetchTab(activeTab.value))

const chatOpen = ref(false)
</script>

<template>
  <div>
    <!-- Breadcrumb -->
    <div class="flex items-center gap-2 mb-6 text-sm text-muted-foreground">
      <NuxtLink to="/" class="inline-flex items-center gap-1 hover:text-foreground transition-colors">
        <ArrowLeft class="h-3.5 w-3.5" />
        Search
      </NuxtLink>
      <span>/</span>
      <span class="text-foreground font-medium">{{ ticker }}</span>
    </div>

    <!-- Company header -->
    <div v-if="profileLoading" class="mb-8">
      <Skeleton class="h-8 w-48 mb-2" />
      <Skeleton class="h-4 w-96" />
    </div>
    <div v-else-if="company" class="mb-8">
      <div class="flex items-start justify-between">
        <div>
          <div class="flex items-center gap-3 mb-1">
            <h1 class="text-2xl font-bold tracking-tight">{{ company.name || ticker }}</h1>
            <Badge variant="secondary" class="text-xs">{{ ticker }}</Badge>
          </div>
          <div class="flex items-center gap-3 text-sm text-muted-foreground">
            <span v-if="company.industry">{{ company.industry }}</span>
            <span v-if="company.sic_code" class="text-xs">SIC {{ company.sic_code }}</span>
            <span v-if="company.cik" class="text-xs">CIK {{ company.cik }}</span>
          </div>
        </div>
        <div class="flex items-center gap-2">
          <!-- Period selector -->
          <Select
            v-model="periodType"
            :options="periodOptions"
            placeholder="Period"
            class="w-32 h-9"
          />
          <!-- Chat toggle -->
          <Sheet v-model:open="chatOpen">
            <SheetTrigger as-child>
              <Button variant="outline" size="sm" class="gap-2">
                <MessageSquare class="h-4 w-4" />
                Ask AI
              </Button>
            </SheetTrigger>
            <SheetContent side="right" class="w-full sm:max-w-lg p-0 flex flex-col">
              <SheetHeader class="p-6 pb-0">
                <SheetTitle>AI Research Assistant</SheetTitle>
              </SheetHeader>
              <div class="flex-1 overflow-hidden">
                <CompanyChatPanel :ticker="tickerRef" />
              </div>
            </SheetContent>
          </Sheet>
        </div>
      </div>
    </div>

    <!-- KPI summary row -->
    <CompanyKpiCards
      v-if="kpi"
      :data="kpi"
      :ticker="ticker"
      class="mb-6"
    />

    <!-- Tabs -->
    <Tabs v-model="activeTab" class="w-full">
      <TabsList class="w-full justify-start gap-0.5 bg-transparent p-0 border-b rounded-none h-auto">
        <TabsTrigger
          v-for="t in [
            { value: 'income', label: 'Income Statement' },
            { value: 'balance', label: 'Balance Sheet' },
            { value: 'cashflow', label: 'Cash Flow' },
            { value: 'health', label: 'Financial Health' },
            { value: 'ratios', label: 'Ratios' },
            { value: 'growth', label: 'Growth & Margins' },
            { value: 'quarterly', label: 'Quarterly' },
            { value: 'filings', label: 'Filings' },
          ]"
          :key="t.value"
          :value="t.value"
          class="rounded-none border-b-2 border-transparent data-[state=active]:border-foreground data-[state=active]:bg-transparent data-[state=active]:shadow-none px-4 py-2.5 text-sm"
        >
          {{ t.label }}
        </TabsTrigger>
      </TabsList>

      <!-- Tab content -->
      <div class="mt-6">
        <div v-if="tabLoading" class="space-y-4">
          <Skeleton class="h-64 w-full rounded-lg" />
          <Skeleton class="h-48 w-full rounded-lg" />
        </div>

        <TabsContent value="income">
          <CompanyIncomeTab v-if="income" :data="income" :ticker="ticker" />
        </TabsContent>

        <TabsContent value="balance">
          <CompanyBalanceSheetTab v-if="balance" :data="balance" :ticker="ticker" />
        </TabsContent>

        <TabsContent value="cashflow">
          <CompanyCashFlowTab v-if="cashflow" :data="cashflow" :ticker="ticker" />
        </TabsContent>

        <TabsContent value="health">
          <CompanyHealthTab v-if="health" :data="health" :ticker="ticker" />
        </TabsContent>

        <TabsContent value="ratios">
          <CompanyRatiosTab v-if="ratios" :data="ratios" :ticker="ticker" />
        </TabsContent>

        <TabsContent value="growth">
          <CompanyGrowthTab v-if="growth" :data="growth" :ticker="ticker" />
        </TabsContent>

        <TabsContent value="quarterly">
          <CompanyQuarterlyTab v-if="quarterly" :data="quarterly" :ticker="ticker" />
        </TabsContent>

        <TabsContent value="filings">
          <CompanyFilingsTab :filings="filings" :ticker="ticker" @refresh="fetchTab('filings')" />
        </TabsContent>
      </div>
    </Tabs>
  </div>
</template>
