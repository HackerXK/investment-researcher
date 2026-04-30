/**
 * Chat composable — SSE streaming to /api/chat.
 */
import { ref, type Ref } from 'vue'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
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
            if (data === '[DONE]') continue

            let parsed: any
            try {
              parsed = JSON.parse(data)
            } catch {
              // non-JSON SSE line, skip
              continue
            }

            if (parsed.error) throw new Error(parsed.error)

            if (parsed.progress) {
              progress.value = parsed.progress
              continue
            }

            const delta = parsed.token ?? parsed.choices?.[0]?.delta?.content
            if (delta) {
              progress.value = ''
              // Update the last assistant message reactively
              const idx = messages.value.length - 1
              messages.value[idx] = {
                ...messages.value[idx],
                content: messages.value[idx].content + delta,
              }
            }
          }
        }
      }
    } catch (e: any) {
      progress.value = ''
      const idx = messages.value.length - 1
      messages.value[idx] = {
        ...messages.value[idx],
        content: messages.value[idx].content || `Error: ${e.message}`,
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
