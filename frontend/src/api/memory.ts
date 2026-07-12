import { requestJson } from './client'

export type MemoryKind =
  | 'fact'
  | 'preference'
  | 'summary'
  | 'definition'
  | 'instruction'
  | 'episodic'

export type MemoryScope = 'global' | 'user' | 'session' | 'context'
export type MemorySort =
  | 'default'
  | 'priority'
  | 'relevance'
  | 'confidence'
  | 'updated_at'
  | 'created_at'
  | 'memory_id'

export type MemoryItem = {
  memory_id: string
  owner_id?: string | null
  content: string
  kind?: MemoryKind
  scope?: MemoryScope
  scope_id?: string | null
  tags?: string[]
  priority?: number
  relevance?: number
  confidence?: number
  is_enabled?: boolean
  expires_at?: string | null
  created_at?: string
  updated_at?: string
  metadata?: Record<string, unknown>
}

export type MemoryQuery = {
  text?: string | null
  scope?: MemoryScope | null
  scope_id?: string | null
  kinds?: MemoryKind[]
  tags?: string[]
  minimum_relevance?: number | null
  minimum_confidence?: number | null
  include_disabled?: boolean
  include_expired?: boolean
  deduplicate?: boolean
  sort?: MemorySort
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

export type MemoryListParams = {
  text?: string
  scope?: MemoryScope | ''
  scope_id?: string
  kind?: MemoryKind | ''
  tag?: string
  include_disabled?: boolean
  include_expired?: boolean
  deduplicate?: boolean
  sort?: MemorySort
}

export function listMemories(params: MemoryListParams = {}): Promise<MemoryItem[]> {
  const searchParams = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') {
      return
    }
    searchParams.append(key, String(value))
  })
  const query = searchParams.toString()
  return requestJson<MemoryItem[]>(query ? `/memories?${query}` : '/memories')
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

export function replaceMemory(memoryId: string, memory: MemoryItem): Promise<MemoryItem> {
  return requestJson<MemoryItem>(`/memories/${encodeURIComponent(memoryId)}`, {
    method: 'PUT',
    body: memory,
  })
}

export function enableMemory(memoryId: string): Promise<MemoryItem> {
  return requestJson<MemoryItem>(`/memories/${encodeURIComponent(memoryId)}/enable`, {
    method: 'POST',
  })
}

export function disableMemory(memoryId: string): Promise<MemoryItem> {
  return requestJson<MemoryItem>(`/memories/${encodeURIComponent(memoryId)}/disable`, {
    method: 'POST',
  })
}

export function deleteMemory(memoryId: string): Promise<void> {
  return requestJson<void>(`/memories/${encodeURIComponent(memoryId)}/delete`, {
    method: 'POST',
  })
}
