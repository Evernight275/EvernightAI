import { requestJson } from './client'
import type { ChatRequest, ChatSkill, Content } from './content'
import type { MemoryQuery } from './memory'
import type { ToolDefinition } from './tools'

export type Context = {
  context_id: string
  messages?: Content[]
  metadata?: Record<string, unknown>
}

export function createContext(context: Context, signal?: AbortSignal): Promise<Context> {
  return requestJson<Context>('/contexts', {
    method: 'POST',
    body: context,
    signal,
  })
}

export function listContexts(): Promise<Context[]> {
  return requestJson<Context[]>('/contexts')
}

export function getContext(contextId: string, signal?: AbortSignal): Promise<Context> {
  return requestJson<Context>(`/contexts/${encodeURIComponent(contextId)}`, { signal })
}

export function appendContextMessage(contextId: string, message: Content): Promise<Context> {
  return requestJson<Context>(`/contexts/${encodeURIComponent(contextId)}/messages`, {
    method: 'POST',
    body: message,
  })
}

export function replaceContext(
  contextId: string,
  context: Context,
  signal?: AbortSignal,
): Promise<Context> {
  return requestJson<Context>(`/contexts/${encodeURIComponent(contextId)}`, {
    method: 'PUT',
    body: context,
    signal,
  })
}

export function deleteContext(contextId: string, signal?: AbortSignal): Promise<void> {
  return requestJson<void>(`/contexts/${encodeURIComponent(contextId)}/delete`, {
    method: 'POST',
    signal,
  })
}

export type ContextComposePreviewRequest = {
  model_id: string
  messages?: Content[]
  memory_query?: MemoryQuery | null
  skills?: ChatSkill[] | null
  tools?: ToolDefinition[] | null
  metadata?: Record<string, unknown> | null
}

export function composeContextPreview(
  contextId: string,
  request: ContextComposePreviewRequest,
): Promise<ChatRequest> {
  return requestJson<ChatRequest>(`/contexts/${encodeURIComponent(contextId)}/compose-preview`, {
    method: 'POST',
    body: request,
  })
}
