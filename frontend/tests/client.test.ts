import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  requestJson,
  requestSse,
  setAccessToken,
  setApiKey,
} from '../src/api/client'

describe('API client', () => {
  beforeEach(() => {
    const storage = new MemoryStorage()
    vi.stubGlobal('localStorage', storage)
    vi.stubGlobal('window', {
      EVERNIGHTAI_API_BASE: '',
      EVERNIGHTAI_API_KEY: '',
      EVERNIGHTAI_ACCESS_TOKEN: '',
      dispatchEvent: vi.fn(),
    })
    vi.restoreAllMocks()
  })

  it('sends exactly one credential type', async () => {
    const fetchMock = vi.fn()
      .mockImplementation(async () => new Response('{"status":"ok"}', {
        headers: { 'content-type': 'application/json' },
      }))
    vi.stubGlobal('fetch', fetchMock)

    setAccessToken('access-token')
    setApiKey('api-key')
    await requestJson('/health')

    const firstHeaders = requestHeaders(fetchMock, 0)
    expect(firstHeaders['x-evernight-api-key']).toBe('api-key')
    expect(firstHeaders.authorization).toBeUndefined()

    setAccessToken('access-token')
    await requestJson('/health')

    const secondHeaders = requestHeaders(fetchMock, 1)
    expect(secondHeaders.authorization).toBe('Bearer access-token')
    expect(secondHeaders['x-evernight-api-key']).toBeUndefined()
  })

  it('preserves structured API error details', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: {
        type: 'ValidationError',
        message: 'Invalid request',
        detail: [{ field: 'model_id' }],
      },
    }), {
      status: 400,
      headers: {
        'content-type': 'application/json',
        'x-request-id': 'request-1',
      },
    })))

    const error = await requestJson('/chat').catch((reason: unknown) => reason)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      message: 'Invalid request',
      status: 400,
      path: '/chat',
      requestId: 'request-1',
      errorType: 'ValidationError',
      detail: [{ field: 'model_id' }],
    })
  })

  it('reassembles SSE events split across response chunks', async () => {
    const encoder = new TextEncoder()
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('event: chat.message_delta\ndata: {"text_'))
        controller.enqueue(encoder.encode('delta":"hello"}\n\nid: 2\ndata: [DONE]\n\n'))
        controller.close()
      },
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(stream, {
      headers: { 'content-type': 'text/event-stream' },
    })))
    const events: Array<{ event: string; data: string; id?: string }> = []

    await requestSse('/chat/stream', { method: 'POST', body: {} }, (event) => {
      events.push(event)
    })

    expect(events).toEqual([
      { event: 'chat.message_delta', data: '{"text_delta":"hello"}' },
      { event: 'message', id: '2', data: '[DONE]' },
    ])
  })
})

function requestHeaders(fetchMock: ReturnType<typeof vi.fn>, callIndex: number) {
  const options = fetchMock.mock.calls[callIndex]?.[1] as RequestInit
  return options.headers as Record<string, string>
}

class MemoryStorage implements Storage {
  private readonly values = new Map<string, string>()

  get length(): number {
    return this.values.size
  }

  clear(): void {
    this.values.clear()
  }

  getItem(key: string): string | null {
    return this.values.get(key) ?? null
  }

  key(index: number): string | null {
    return [...this.values.keys()][index] ?? null
  }

  removeItem(key: string): void {
    this.values.delete(key)
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value)
  }
}
