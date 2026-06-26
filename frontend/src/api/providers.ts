import { requestJson } from './client'

export type ProviderType = 'openai' | 'openai_responses' | 'google' | 'anthropic'

export type ProviderModelCapability =
  | 'chat'
  | 'tool_call'
  | 'image_generation'
  | 'image_recognition'
  | 'video_generation'
  | 'video_recognition'

export type ProviderModelConfig = {
  model_id: string
  timeout?: string | number
  capabilities?: ProviderModelCapability[]
  metadata?: Record<string, unknown>
}

export type ProviderConfig = {
  provider_id: string
  name: string
  type: ProviderType
  is_enabled?: boolean
  api_key?: string | null
  base_url?: string | null
  model?: Record<string, ProviderModelConfig>
  metadata?: Record<string, unknown>
}

export type ProviderInfo = Omit<ProviderConfig, 'api_key'>

export function createProvider(config: ProviderConfig): Promise<ProviderInfo> {
  return requestJson<ProviderInfo>('/providers', {
    method: 'POST',
    body: config,
  })
}

export function listProviders(): Promise<ProviderInfo[]> {
  return requestJson<ProviderInfo[]>('/providers')
}

export function listProviderModels(providerId: string): Promise<ProviderModelConfig[]> {
  return requestJson<ProviderModelConfig[]>(
    `/providers/${encodeURIComponent(providerId)}/models`,
  )
}

export function getProviderModel(
  providerId: string,
  modelId: string,
): Promise<ProviderModelConfig> {
  return requestJson<ProviderModelConfig>(
    `/providers/${encodeURIComponent(providerId)}/models/${encodeURIComponent(modelId)}`,
  )
}

export function providerSupports(
  providerId: string,
  capability: ProviderModelCapability,
): Promise<boolean> {
  const params = new URLSearchParams({ capability })
  return requestJson<boolean>(`/providers/${encodeURIComponent(providerId)}/supports?${params}`)
}

export function deleteProvider(providerId: string): Promise<void> {
  return requestJson<void>(`/providers/${encodeURIComponent(providerId)}/delete`, {
    method: 'POST',
  })
}
