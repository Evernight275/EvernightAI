import { requestJson } from './client'

export type LogLevel = 'debug' | 'info' | 'warning' | 'error' | 'critical' | string

export type LogEntry = {
  index: number
  timestamp: string
  level: LogLevel
  logger: string
  message: string
  module?: string | null
  function?: string | null
  line?: number | null
  metadata?: Record<string, unknown>
}

export function listLogs(params: { limit?: number; after?: number } = {}): Promise<LogEntry[]> {
  const query = new URLSearchParams()
  if (params.limit !== undefined) {
    query.set('limit', String(params.limit))
  }
  if (params.after !== undefined) {
    query.set('after', String(params.after))
  }

  const suffix = query.toString()
  return requestJson<LogEntry[]>(`/logs${suffix ? `?${suffix}` : ''}`)
}

export function clearLogs(): Promise<void> {
  return requestJson<void>('/logs/clear', {
    method: 'POST',
  })
}
