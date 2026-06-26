import { deleteJson, requestJson } from './client'

export type MemoryKind =
  | 'fact'
  | 'preference'
  | 'summary'
  | 'definition'
  | 'instruction'
  | 'episodic'

export type MemoryScope = 'global' | 'user' | 'session' | 'context'

export type MemoryItem = {
  memory_id: string
  content: string
  kind?: MemoryKind
  scope?: MemoryScope
  scope_id?: string | null
  tags?: string[]
  priority?: number
  is_enabled?: boolean
  metadata?: Record<string, unknown>
}

export type MemoryQuery = {
  scope?: MemoryScope | null
  scope_id?: string | null
  kinds?: MemoryKind[]
  tags?: string[]
  limit?: number | null
  metadata?: Record<string, unknown>
}

export type MemorySelection = {
  memories: MemoryItem[]
  metadata?: Record<string, unknown>
}

export function createMemory(memory: MemoryItem): Promise<MemoryItem> {
  return requestJson<MemoryItem>('/memories', {
    method: 'POST',
    body: memory,
  })
}

export function listMemories(): Promise<MemoryItem[]> {
  return requestJson<MemoryItem[]>('/memories')
}

export function getMemory(memoryId: string): Promise<MemoryItem> {
  return requestJson<MemoryItem>(`/memories/${encodeURIComponent(memoryId)}`)
}

export function selectMemories(query: MemoryQuery | null = null): Promise<MemorySelection> {
  return requestJson<MemorySelection>('/memories/select', {
    method: 'POST',
    body: query,
  })
}

export function deleteMemory(memoryId: string): Promise<void> {
  return deleteJson(`/memories/${encodeURIComponent(memoryId)}`)
}
