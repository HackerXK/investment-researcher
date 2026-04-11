<script setup lang="ts">
import { ref, nextTick, watch } from 'vue'
import { Send, Trash2, Bot, User } from 'lucide-vue-next'
import { Button } from '~/components/ui/button'
import { ScrollArea } from '~/components/ui/scroll-area'
import { useChat, type ChatMessage } from '~/composables/useChat'
import { marked } from 'marked'

const props = defineProps<{ ticker: string }>()

const tickerRef = ref(props.ticker)
watch(() => props.ticker, (v) => { tickerRef.value = v })

const { messages, streaming, send, clear } = useChat(tickerRef)

const input = ref('')
const messagesEnd = ref<HTMLElement>()

function onSubmit() {
  if (!input.value.trim()) return
  send(input.value)
  input.value = ''
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    onSubmit()
  }
}

// Auto-scroll on new messages
watch(
  () => messages.value.length > 0 ? messages.value[messages.value.length - 1].content : '',
  async () => {
    await nextTick()
    messagesEnd.value?.scrollIntoView({ behavior: 'smooth' })
  },
)

function renderMarkdown(content: string): string {
  if (!content) return ''
  return marked.parse(content, { async: false }) as string
}

const suggestions = [
  `What are ${props.ticker}'s key competitive advantages?`,
  `Analyze ${props.ticker}'s profitability trends`,
  `Is ${props.ticker}'s balance sheet healthy?`,
  `Summarize ${props.ticker}'s latest 10-K risks`,
]
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Messages area -->
    <ScrollArea class="flex-1 px-6 py-4">
      <!-- Empty state -->
      <div v-if="messages.length === 0" class="flex flex-col items-center justify-center h-full py-12">
        <div class="flex h-12 w-12 items-center justify-center rounded-2xl bg-muted mb-4">
          <Bot class="h-6 w-6 text-muted-foreground" />
        </div>
        <p class="text-sm text-muted-foreground mb-6 text-center max-w-xs">
          Ask questions about {{ ticker }}'s financials, filings, and business strategy.
        </p>
        <div class="space-y-2 w-full max-w-xs">
          <button
            v-for="s in suggestions"
            :key="s"
            class="w-full text-left text-xs rounded-lg border px-3 py-2 text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors"
            @click="send(s)"
          >
            {{ s }}
          </button>
        </div>
      </div>

      <!-- Messages -->
      <div v-else class="space-y-4">
        <div
          v-for="(msg, idx) in messages"
          :key="idx"
          class="flex gap-3"
          :class="msg.role === 'user' ? 'justify-end' : ''"
        >
          <!-- Assistant message -->
          <template v-if="msg.role === 'assistant'">
            <div class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted">
              <Bot class="h-3.5 w-3.5 text-muted-foreground" />
            </div>
            <div class="max-w-[85%] rounded-2xl rounded-tl-md bg-muted px-4 py-3">
              <div
                v-if="msg.content"
                class="prose prose-sm prose-slate max-w-none text-sm [&_p]:mb-2 [&_p:last-child]:mb-0 [&_code]:text-xs [&_pre]:bg-background [&_pre]:rounded [&_pre]:p-2"
                v-html="renderMarkdown(msg.content)"
              />
              <div v-else class="flex items-center gap-1.5">
                <div class="h-1.5 w-1.5 rounded-full bg-muted-foreground/40 animate-bounce [animation-delay:0ms]" />
                <div class="h-1.5 w-1.5 rounded-full bg-muted-foreground/40 animate-bounce [animation-delay:150ms]" />
                <div class="h-1.5 w-1.5 rounded-full bg-muted-foreground/40 animate-bounce [animation-delay:300ms]" />
              </div>
            </div>
          </template>

          <!-- User message -->
          <template v-else>
            <div class="max-w-[85%] rounded-2xl rounded-tr-md bg-foreground text-background px-4 py-3">
              <p class="text-sm">{{ msg.content }}</p>
            </div>
            <div class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-foreground">
              <User class="h-3.5 w-3.5 text-background" />
            </div>
          </template>
        </div>
        <div ref="messagesEnd" />
      </div>
    </ScrollArea>

    <!-- Input area -->
    <div class="border-t p-4">
      <div class="flex items-center gap-2">
        <Button
          v-if="messages.length > 0"
          variant="ghost"
          size="icon"
          class="shrink-0 h-9 w-9"
          @click="clear()"
        >
          <Trash2 class="h-4 w-4" />
        </Button>
        <div class="relative flex-1">
          <textarea
            v-model="input"
            :disabled="streaming"
            placeholder="Ask about this company..."
            rows="1"
            class="flex w-full rounded-xl border border-input bg-background px-4 py-2.5 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 resize-none"
            @keydown="onKeydown"
          />
        </div>
        <Button
          size="icon"
          class="shrink-0 h-9 w-9 rounded-xl"
          :disabled="!input.trim() || streaming"
          @click="onSubmit"
        >
          <Send class="h-4 w-4" />
        </Button>
      </div>
    </div>
  </div>
</template>
