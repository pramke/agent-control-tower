/** SSE 流式读取工具 — 连接 agent trace 端点，按事件类型解析并回调。 */
import { getAccessToken } from '../api/client'

/** SSE event handler callback */
export type SSEHandler = (type: string, data: Record<string, unknown>) => void

/** Read SSE stream from an agent run and invoke handler for each event. */
export async function readSSE(
  traceId: string,
  onEvent: SSEHandler,
  signal?: AbortSignal,
): Promise<void> {
  const headers: Record<string, string> = {}
  const token = getAccessToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(`/api/agents/${traceId}/stream`, { headers, signal })
  if (!res.ok || !res.body) throw new Error(`Stream failed: HTTP ${res.status}`)
  const reader = res.body.getReader()
  signal?.addEventListener('abort', () => reader.cancel())
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    // 增量解码并累积到缓冲区，SSE 事件以双换行分隔
    buf += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buf.indexOf('\n\n')) !== -1) {
      const raw = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      if (!raw || raw.startsWith(':')) continue
      let eventType = 'message'
      let data = ''
      for (const line of raw.split('\n')) {
        if (line.startsWith('event:')) eventType = line.slice(6).trim()
        else if (line.startsWith('data:')) data += line.slice(5).trim()
      }
      if (data) {
        try {
          onEvent(eventType, JSON.parse(data))
        } catch {
          // ignore malformed
        }
      }
    }
  }
}
