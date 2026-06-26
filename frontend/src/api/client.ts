export const apiBase = window.EVERNIGHTAI_API_BASE || ''
const apiKeyStorageKey = 'evernight.apiKey'

type RequestOptions = {
  method?: string
  body?: unknown
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

export async function deleteJson(path: string): Promise<void> {
  await requestJson<void>(path, { method: 'DELETE' })
}
