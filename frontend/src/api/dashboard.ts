import { listAgentRuns } from './agentRuns'
import { getHealth } from './health'
import {
  listProviderModels,
  listProviders,
  type ProviderInfo,
  type ProviderModelConfig,
} from './providers'
import { listSessions } from './sessions'
import { listTools } from './tools'

export async function fetchDashboard() {
  const [healthResult, sessionsResult, toolsResult, runsResult, providersResult] = await Promise.allSettled([
    getHealth(),
    listSessions(),
    listTools(),
    listAgentRuns(),
    listProviders(),
  ])
  const providers = providersResult.status === 'fulfilled' && Array.isArray(providersResult.value)
    ? providersResult.value
    : []
  const providerModelGroups = await fetchProviderModelGroups(providers)

  return {
    healthOk: healthResult.status === 'fulfilled' && healthResult.value.status === 'ok',
    sessions: sessionsResult.status === 'fulfilled' && Array.isArray(sessionsResult.value)
      ? sessionsResult.value
      : [],
    tools: toolsResult.status === 'fulfilled' && Array.isArray(toolsResult.value)
      ? toolsResult.value
      : [],
    runs: runsResult.status === 'fulfilled' && Array.isArray(runsResult.value)
      ? runsResult.value
      : [],
    providers,
    providerModelGroups,
    error: firstRejectedReason([
      healthResult,
      sessionsResult,
      toolsResult,
      runsResult,
      providersResult,
    ]),
  }
}

export async function fetchProviderModels() {
  const providers = await listProviders()
  return {
    providers,
    providerModelGroups: await fetchProviderModelGroups(providers),
  }
}

export type ProviderModelGroup = {
  provider: ProviderInfo
  models: ProviderModelConfig[]
}

async function fetchProviderModelGroups(providers: ProviderInfo[]): Promise<ProviderModelGroup[]> {
  const results = await Promise.allSettled(
    providers.map(async (provider) => ({
      provider,
      models: await listProviderModels(provider.provider_id),
    })),
  )

  return results.map((result, index) => {
    if (result.status === 'fulfilled') {
      return result.value
    }

    const provider = providers[index]
    return {
      provider,
      models: Object.values(provider.model || {}),
    }
  })
}

function firstRejectedReason(results: Array<PromiseSettledResult<unknown>>): string | null {
  const failed = results.find((result) => result.status === 'rejected')
  if (!failed || failed.status !== 'rejected') {
    return null
  }

  return failed.reason instanceof Error ? failed.reason.message : '后端接口请求失败'
}
