<script setup lang="ts">
import { Search, MessageSquare, TrendingUp } from 'lucide-vue-next'
</script>

<template>
  <div class="min-h-screen bg-background">
    <!-- Top nav -->
    <header class="sticky top-0 z-40 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div class="container mx-auto flex h-14 items-center px-6">
        <NuxtLink to="/" class="flex items-center gap-2.5 mr-8">
          <div class="flex h-7 w-7 items-center justify-center rounded-md bg-foreground">
            <TrendingUp class="h-4 w-4 text-background" />
          </div>
          <span class="text-sm font-semibold tracking-tight">Investment Researcher</span>
        </NuxtLink>
        <div class="flex-1" />
        <nav class="flex items-center gap-1 text-sm text-muted-foreground">
          <NuxtLink
            to="/"
            class="flex items-center gap-1.5 rounded-md px-3 py-1.5 transition-colors hover:text-foreground hover:bg-accent"
          >
            <Search class="h-3.5 w-3.5" />
            Search
          </NuxtLink>
        </nav>
      </div>
    </header>

    <!-- Main content -->
    <main class="container mx-auto px-6 py-6">
      <slot />
    </main>
  </div>
</template>
