import { requestJson } from './client'

export type LogLevel = 'debug' | 'info' | 'warning' | 'error' | 'critical' | string

export type Log = {
  sequence: number | null
  occurred_at: string | null
  level: LogLevel
  source: string
  message: string
  trace_id?: string | null
  span_id?: string | null
  error_type?: string | null
  error_message?: string | null
  metadata?: Record<string, unknown>
}

export function listLogs(params: { limit?: number; after?: number } = {}): Promise<Log[]> {
  const query = new URLSearchParams()
  if (params.limit !== undefined) {
    query.set('limit', String(params.limit))
  }
  if (params.after !== undefined) {
    query.set('after', String(params.after))
  }

  const suffix = query.toString()
  return requestJson<Log[]>(`/logs${suffix ? `?${suffix}` : ''}`)
}

export function clearLogs(): Promise<void> {
  return requestJson<void>('/logs/clear', {
    method: 'POST',
  })
}
