export const apiBase = normalizeApiBase(
  window.EVERNIGHTAI_API_BASE || import.meta.env.VITE_EVERNIGHTAI_API_BASE || '',
)
const apiKeyStorageKey = 'evernight.apiKey'

type RequestOptions = {
  method?: string
  body?: unknown
}

export type SseEvent = {
  event: string
  data: string
  id?: string
}

export function getApiKey(): string {
  return localStorage.getItem(apiKeyStorageKey) || window.EVERNIGHTAI_API_KEY || ''
}

export function setApiKey(apiKey: string) {
  const cleanApiKey = apiKey.trim()
  if (cleanApiKey) {
    localStorage.setItem(apiKeyStorageKey, cleanApiKey)
  } else {
    localStorage.removeItem(apiKeyStorageKey)
  }
  window.dispatchEvent(new CustomEvent('evernight-api-key-change'))
}

export async function requestJson<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const apiKey = getApiKey()
  const response = await fetch(`${apiBase}${path}`, {
    method: options.method || 'GET',
    headers: {
      accept: 'application/json',
      ...(apiKey ? { 'x-evernight-api-key': apiKey } : {}),
      ...(options.body === undefined ? {} : { 'content-type': 'application/json' }),
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })

  if (!response.ok) {
    throw new Error(`${path} returned ${response.status}`)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return response.json() as Promise<T>
}

export async function requestSse(
  path: string,
  options: RequestOptions,
  onEvent: (event: SseEvent) => void,
): Promise<void> {
  const apiKey = getApiKey()
  const response = await fetch(`${apiBase}${path}`, {
    method: options.method || 'POST',
    headers: {
      accept: 'text/event-stream',
      ...(apiKey ? { 'x-evernight-api-key': apiKey } : {}),
      ...(options.body === undefined ? {} : { 'content-type': 'application/json' }),
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })

  if (!response.ok) {
    throw new Error(`${path} returned ${response.status}`)
  }

  if (!response.body) {
    throw new Error(`${path} did not return a stream`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) {
      break
    }

    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split(/\r?\n\r?\n/)
    buffer = parts.pop() || ''
    parts.forEach((part) => emitSsePart(part, onEvent))
  }

  buffer += decoder.decode()
  if (buffer.trim() !== '') {
    emitSsePart(buffer, onEvent)
  }
}

function emitSsePart(part: string, onEvent: (event: SseEvent) => void) {
  const lines = part.split(/\r?\n/)
  const event: SseEvent = {
    event: 'message',
    data: '',
  }
  const dataLines: string[] = []

  lines.forEach((line) => {
    if (line === '' || line.startsWith(':')) {
      return
    }

    const separatorIndex = line.indexOf(':')
    const field = separatorIndex === -1 ? line : line.slice(0, separatorIndex)
    const rawValue = separatorIndex === -1 ? '' : line.slice(separatorIndex + 1)
    const value = rawValue.startsWith(' ') ? rawValue.slice(1) : rawValue

    if (field === 'event') {
      event.event = value
    } else if (field === 'id') {
      event.id = value
    } else if (field === 'data') {
      dataLines.push(value)
    }
  })

  event.data = dataLines.join('\n')
  onEvent(event)
}

function normalizeApiBase(value: string): string {
  return value.trim().replace(/\/+$/, '')
}
