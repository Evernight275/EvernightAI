import { requestJson } from './client'

export type HealthResponse = {
  status: 'ok'
}

export type ReadinessResponse = {
  status: 'ready'
}

export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return requestJson<HealthResponse>('/health', { signal })
}

export function getReadiness(signal?: AbortSignal): Promise<ReadinessResponse> {
  return requestJson<ReadinessResponse>('/ready', { signal })
}
