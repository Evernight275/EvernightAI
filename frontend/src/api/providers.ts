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
  discover_models?: boolean
  api_key_secret_ref?: string | null
  api_key?: string | null
  base_url?: string | null
  model?: Record<string, ProviderModelConfig>
  metadata?: Record<string, unknown>
}

export type ProviderInfo = Pick<ProviderConfig, 'provider_id' | 'name' | 'type' | 'is_enabled' | 'model' | 'metadata'>

export function createProvider(config: ProviderConfig): Promise<ProviderInfo> {
  return requestJson<ProviderInfo>('/providers', {
    method: 'POST',
    body: config,
  })
}

export function listProviders(signal?: AbortSignal): Promise<ProviderInfo[]> {
  return requestJson<ProviderInfo[]>('/providers', { signal })
}

export function listProviderModels(
  providerId: string,
  signal?: AbortSignal,
): Promise<ProviderModelConfig[]> {
  return requestJson<ProviderModelConfig[]>(
    `/providers/${encodeURIComponent(providerId)}/models`,
    { signal },
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
