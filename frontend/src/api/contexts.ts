import { deleteJson, requestJson } from './client'
import type { Content } from './content'

export type Context = {
  context_id: string
  messages?: Content[]
  metadata?: Record<string, unknown>
}

export function createContext(context: Context): Promise<Context> {
  return requestJson<Context>('/contexts', {
    method: 'POST',
    body: context,
  })
}

export function listContexts(): Promise<Context[]> {
  return requestJson<Context[]>('/contexts')
}

export function getContext(contextId: string): Promise<Context> {
  return requestJson<Context>(`/contexts/${encodeURIComponent(contextId)}`)
}

export function appendContextMessage(contextId: string, message: Content): Promise<Context> {
  return requestJson<Context>(`/contexts/${encodeURIComponent(contextId)}/messages`, {
    method: 'POST',
    body: message,
  })
}

export function replaceContext(contextId: string, context: Context): Promise<Context> {
  return requestJson<Context>(`/contexts/${encodeURIComponent(contextId)}`, {
    method: 'PUT',
    body: context,
  })
}

export function deleteContext(contextId: string): Promise<void> {
  return deleteJson(`/contexts/${encodeURIComponent(contextId)}`)
}
