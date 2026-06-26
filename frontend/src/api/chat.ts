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

    onEvent(JSON.parse(rawEvent.data) as ChatStreamEvent, rawEvent)
  })
}
