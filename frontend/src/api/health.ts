import { requestJson } from './client'

export type HealthResponse = {
  status?: string
}

export function getHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>('/health')
}
