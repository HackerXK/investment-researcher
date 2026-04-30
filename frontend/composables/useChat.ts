/**
 * Chat composable — SSE streaming to /api/chat.
 */
import { ref, type Ref } from 'vue'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

type ChatSSEEvent =
  | { type: 'done' }
  | { type: 'error'; error: string }
  | { type: 'progress'; progress: string }
  | { type: 'token'; token: string }


function parseChatSSEEvent(data: string): ChatSSEEvent | null {
  if (data === '[DONE]') {
    return { type: 'done' }
  }

  let parsed: any
  try {
    parsed = JSON.parse(data)
  } catch {
    return null
  }

  if (typeof parsed.error === 'string' && parsed.error) {
    return { type: 'error', error: parsed.error }
  }

  if (typeof parsed.progress === 'string' && parsed.progress) {
    return { type: 'progress', progress: parsed.progress }
  }

  const token =
    typeof parsed.token === 'string'
      ? parsed.token
      : parsed.choices?.[0]?.delta?.content

  if (typeof token === 'string' && token) {
    return { type: 'token', token }
  }

  return null
}


function appendAssistantToken(messages: ChatMessage[], token: string) {
  const idx = messages.length - 1
  messages[idx] = {
    ...messages[idx],
    content: messages[idx].content + token,
  }
}


function getErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message
  }
  return String(error)
}

function createChatSessionId() {
  const uuid = globalThis.crypto?.randomUUID?.()
  if (uuid) {
    return `web-chat-${uuid}`
  }
  return `web-chat-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function useChat(ticker: Ref<string>) {
  const messages = ref<ChatMessage[]>([])
  const streaming = ref(false)
  const progress = ref('')
  const sessionId = ref(createChatSessionId())

  async function send(text: string) {
    if (!text.trim() || streaming.value) return

    messages.value.push({ role: 'user', content: text })
    const assistantMsg: ChatMessage = { role: 'assistant', content: '' }
    messages.value.push(assistantMsg)
    streaming.value = true
    progress.value = ''

    try {
      const body = JSON.stringify({
        message: text,
        ticker: ticker.value || undefined,
        session_id: sessionId.value,
        source: 'web-ui',
        history: messages.value.slice(0, -2).map(m => ({
          role: m.role,
          content: m.content,
        })),
      })

      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
      })

      if (!res.ok) throw new Error(`Chat error: ${res.status}`)

      const reader = res.body?.getReader()
      const decoder = new TextDecoder()
      if (!reader) throw new Error('No response body')

      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6)
            const event = parseChatSSEEvent(data)
            if (!event || event.type === 'done') {
              continue
            }

            if (event.type === 'error') {
              throw new Error(event.error)
            }

            if (event.type === 'progress') {
              progress.value = event.progress
              continue
            }

            if (event.type === 'token') {
              progress.value = ''
              appendAssistantToken(messages.value, event.token)
            }
          }
        }
      }
    } catch (e: unknown) {
      progress.value = ''
      const idx = messages.value.length - 1
      messages.value[idx] = {
        ...messages.value[idx],
        content: messages.value[idx].content || `Error: ${getErrorMessage(e)}`,
      }
    } finally {
      progress.value = ''
      streaming.value = false
    }
  }

  function clear() {
    messages.value = []
    progress.value = ''
    sessionId.value = createChatSessionId()
  }

  return { messages, streaming, progress, send, clear }
}
