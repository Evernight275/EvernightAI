import { requestJson, requestSse, type SseEvent } from './client'
import type { ChatRequest, ChatResponse, ChatSkill, Content } from './content'
import type { MemoryQuery } from './memory'
import type { ToolDefinition } from './tools'

export type ChatStreamEventType =
  | 'raw'
  | 'message_start'
  | 'message_delta'
  | 'message_completed'
  | 'tool_call_start'
  | 'tool_call_delta'
  | 'tool_call_completed'
  | 'usage'
  | 'done'
  | 'error'

export type ChatStreamEvent = {
  event_type: ChatStreamEventType | string
  response_id?: string | null
  model_id?: string | null
  role?: string | null
  content_part?: { text?: string | null; type?: string; [key: string]: unknown } | null
  text_delta?: string | null
  finish_reason?: string | null
  error_type?: string | null
  error_message?: string | null
  metadata?: Record<string, unknown>
}

export type DirectChatRequest = {
  provider_id: string
  request: ChatRequest
}

export type ChatWithContextRequest = {
  provider_id: string
  context_id: string
  model_id: string
  messages: Content[]
  retry_from_message_index?: number | null
  memory_query?: MemoryQuery | null
  skills?: ChatSkill[] | null
  tools?: ToolDefinition[] | null
  metadata?: Record<string, unknown> | null
}

export function chat(request: DirectChatRequest): Promise<ChatResponse> {
  return requestJson<ChatResponse>('/chat', {
    method: 'POST',
    body: request,
  })
}

export function chatWithContext(request: ChatWithContextRequest): Promise<ChatResponse> {
  return requestJson<ChatResponse>('/chat/context', {
    method: 'POST',
    body: request,
  })
}

export function chatWithContextStream(
  request: ChatWithContextRequest,
  onEvent: (event: ChatStreamEvent, rawEvent: SseEvent) => void,
): Promise<void> {
  return requestSse('/chat/context/stream', {
    method: 'POST',
    body: request,
  }, (rawEvent) => {
    if (rawEvent.data === '[DONE]') {
      onEvent({ event_type: 'done' }, rawEvent)
      return
    }

    if (rawEvent.data.trim() === '') {
      return
    }

    if (rawEvent.event === 'error') {
      onEvent(serverErrorToChatEvent(rawEvent), rawEvent)
      return
    }

    if (rawEvent.event !== 'message' && !rawEvent.event.startsWith('chat.')) {
      return
    }

    const event = parseSseJson(rawEvent) as ChatStreamEvent
    if (!event.event_type && rawEvent.event.startsWith('chat.')) {
      event.event_type = rawEvent.event.slice('chat.'.length)
    }
    if (!event.event_type) {
      return
    }

    onEvent(event, rawEvent)
  })
}

function parseSseJson(rawEvent: SseEvent): Record<string, unknown> {
  try {
    const parsed = JSON.parse(rawEvent.data) as unknown
    return isRecord(parsed) ? parsed : {}
  } catch {
    throw new Error(`无法解析流式事件：${rawEvent.event}`)
  }
}

function serverErrorToChatEvent(rawEvent: SseEvent): ChatStreamEvent {
  const payload = parseSseJson(rawEvent)
  const error = isRecord(payload.error) ? payload.error : payload
  return {
    event_type: 'error',
    error_type: typeof error.type === 'string' ? error.type : null,
    error_message: typeof error.message === 'string' ? error.message : '流式响应失败',
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
