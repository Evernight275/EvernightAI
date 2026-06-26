import { requestJson } from './client'
import type { ChatRequest, ChatResponse, ChatSkill, Content } from './content'
import type { MemoryQuery } from './memory'
import type { ToolDefinition } from './tools'

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
