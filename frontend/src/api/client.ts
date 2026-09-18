export const apiBase = normalizeApiBase(
  (typeof window === 'undefined' ? '' : window.EVERNIGHTAI_API_BASE)
    || import.meta.env.VITE_EVERNIGHTAI_API_BASE
    || '',
)

const apiKeyStorageKey = 'evernight.apiKey'
const accessTokenStorageKey = 'evernight.accessToken'
const signedOutStorageKey = 'evernight.signedOut'

export type RequestOptions = {
  credentials?: boolean
  method?: string
  body?: unknown
  headers?: Record<string, string>
  signal?: AbortSignal
}

export type SseEvent = {
  event: string
  data: string
  id?: string
}

type ErrorBody = {
  error?: {
    type?: string
    message?: string
    detail?: unknown
  }
  detail?: unknown
}

export class ApiError extends Error {
  readonly status: number
  readonly path: string
  readonly requestId: string | null
  readonly errorType: string | null
  readonly detail: unknown

  constructor(
    message: string,
    options: {
      status: number
      path: string
      requestId: string | null
      errorType: string | null
      detail: unknown
    },
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = options.status
    this.path = options.path
    this.requestId = options.requestId
    this.errorType = options.errorType
    this.detail = options.detail
  }
}

export function getApiKey(): string {
  if (localStorage.getItem(signedOutStorageKey)) return ''
  if (localStorage.getItem(accessTokenStorageKey)) return ''
  return localStorage.getItem(apiKeyStorageKey) || window.EVERNIGHTAI_API_KEY || ''
}

export function setApiKey(apiKey: string): void {
  const value = apiKey.trim()
  if (value) {
    localStorage.removeItem(signedOutStorageKey)
    localStorage.setItem(apiKeyStorageKey, value)
    localStorage.removeItem(accessTokenStorageKey)
  } else {
    localStorage.removeItem(apiKeyStorageKey)
  }
  window.dispatchEvent(new CustomEvent('evernight-api-key-change'))
}

export function getAccessToken(): string {
  if (localStorage.getItem(signedOutStorageKey)) return ''
  if (localStorage.getItem(apiKeyStorageKey)) return ''
  return localStorage.getItem(accessTokenStorageKey) || window.EVERNIGHTAI_ACCESS_TOKEN || ''
}

export function setAccessToken(accessToken: string): void {
  const value = accessToken.trim()
  if (value) {
    localStorage.removeItem(signedOutStorageKey)
    localStorage.setItem(accessTokenStorageKey, value)
    localStorage.removeItem(apiKeyStorageKey)
  } else {
    localStorage.removeItem(accessTokenStorageKey)
  }
  window.dispatchEvent(new CustomEvent('evernight-access-token-change'))
}

export function signOut(): void {
  localStorage.removeItem(apiKeyStorageKey)
  localStorage.removeItem(accessTokenStorageKey)
  localStorage.setItem(signedOutStorageKey, '1')
  window.dispatchEvent(new CustomEvent('evernight-api-key-change'))
}

export async function requestJson<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const response = await sendRequest(path, options, 'application/json')
  await throwForError(path, response)

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
  const response = await sendRequest(path, options, 'text/event-stream')
  await throwForError(path, response)

  if (!response.body) {
    throw new ApiError(`${path} did not return a stream`, {
      status: response.status,
      path,
      requestId: response.headers.get('x-request-id'),
      errorType: null,
      detail: null,
    })
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
  if (buffer.trim()) {
    emitSsePart(buffer, onEvent)
  }
}

async function sendRequest(
  path: string,
  options: RequestOptions,
  accept: string,
): Promise<Response> {
  const apiKey = options.credentials === false ? '' : getApiKey()
  const accessToken = options.credentials === false ? '' : getAccessToken()
  return fetch(`${apiBase}${normalizePath(path)}`, {
    method: options.method || 'GET',
    headers: {
      accept,
      ...(accessToken ? { authorization: `Bearer ${accessToken}` } : {}),
      ...(!accessToken && apiKey ? { 'x-evernight-api-key': apiKey } : {}),
      ...(options.body === undefined ? {} : { 'content-type': 'application/json' }),
      ...options.headers,
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  })
}

async function throwForError(path: string, response: Response): Promise<void> {
  if (response.ok) {
    return
  }

  const body = await readErrorBody(response)
  const message = response.status === 401
    ? '访问凭证无效或已过期，请在设置中重新验证。'
    : response.status === 403
      ? '当前身份没有执行此操作的权限。'
      : body?.error?.message || `Request failed with status ${response.status}`
  throw new ApiError(message, {
    status: response.status,
    path,
    requestId: response.headers.get('x-request-id'),
    errorType: body?.error?.type || null,
    detail: body?.error?.detail ?? body?.detail ?? null,
  })
}

async function readErrorBody(response: Response): Promise<ErrorBody | null> {
  try {
    return await response.json() as ErrorBody
  } catch {
    return null
  }
}

function emitSsePart(part: string, onEvent: (event: SseEvent) => void): void {
  const event: SseEvent = { event: 'message', data: '' }
  const dataLines: string[] = []

  for (const line of part.split(/\r?\n/)) {
    if (!line || line.startsWith(':')) {
      continue
    }

    const separator = line.indexOf(':')
    const field = separator === -1 ? line : line.slice(0, separator)
    const rawValue = separator === -1 ? '' : line.slice(separator + 1)
    const value = rawValue.startsWith(' ') ? rawValue.slice(1) : rawValue

    if (field === 'event') {
      event.event = value
    } else if (field === 'id') {
      event.id = value
    } else if (field === 'data') {
      dataLines.push(value)
    }
  }

  event.data = dataLines.join('\n')
  onEvent(event)
}

function normalizeApiBase(value: string): string {
  return value.trim().replace(/\/+$/, '')
}

function normalizePath(path: string): string {
  return path.startsWith('/') ? path : `/${path}`
}
