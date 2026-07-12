import { computed, ref, type Ref } from 'vue'
import type {
  AgentRunState,
  ProviderModelCapability,
  ProviderModelGroup,
  Session,
} from '../api'

export type ProviderModelChoice = {
  value: string
  providerId: string
  modelId: string
  label: string
  capabilities: ProviderModelCapability[]
}

export const defaultModelChoice: ProviderModelChoice = {
  value: 'main::gpt-4.1-mini',
  providerId: 'main',
  modelId: 'gpt-4.1-mini',
  label: 'main / gpt-4.1-mini',
  capabilities: [],
}

export function useProviderModels(
  providerModelGroups: Ref<ProviderModelGroup[]>,
  sessions: Ref<Session[]>,
  latestRun: Ref<AgentRunState | undefined>,
) {
  const selectedProviderModel = ref(defaultModelChoice.value)

  const providerModelChoices = computed<ProviderModelChoice[]>(() => {
    const choices = new Map<string, ProviderModelChoice>()

    providerModelGroups.value.forEach(({ provider, models }) => {
      models.forEach((model) => {
        addProviderModelChoice(
          choices,
          provider.provider_id,
          model.model_id,
          provider.name,
          model.capabilities,
        )
      })
    })

    if (choices.size === 0) {
      addProviderModelChoice(choices, defaultModelChoice.providerId, defaultModelChoice.modelId)
    }

    sessions.value.forEach((session) => {
      addProviderModelChoice(choices, session.provider_id, session.model_id)
    })

    if (latestRun.value?.request) {
      addProviderModelChoice(
        choices,
        latestRun.value.request.provider_id,
        latestRun.value.request.model_id,
      )
    }

    return [...choices.values()]
  })

  const selectedProviderModelChoice = computed(() => (
    providerModelChoices.value.find((choice) => choice.value === selectedProviderModel.value)
    || providerModelChoices.value[0]
    || defaultModelChoice
  ))

  const providerModelCount = computed(() => (
    providerModelGroups.value.reduce((total, group) => total + group.models.length, 0)
  ))

  function ensureSelectedProviderModel() {
    if (
      providerModelChoices.value.some((choice) => choice.value === selectedProviderModel.value)
    ) {
      return
    }

    selectedProviderModel.value = providerModelChoices.value[0]?.value || defaultModelChoice.value
  }

  function syncProviderModelFromSession(session: Session) {
    if (!session.provider_id || !session.model_id) {
      return
    }

    selectedProviderModel.value = `${session.provider_id}::${session.model_id}`
  }

  return {
    selectedProviderModel,
    providerModelChoices,
    selectedProviderModelChoice,
    providerModelCount,
    ensureSelectedProviderModel,
    syncProviderModelFromSession,
  }
}

function addProviderModelChoice(
  choices: Map<string, ProviderModelChoice>,
  providerId: string | null | undefined,
  modelId: string | null | undefined,
  providerName?: string | null,
  capabilities: ProviderModelCapability[] = [],
) {
  const cleanProviderId = providerId?.trim()
  const cleanModelId = modelId?.trim()

  if (!cleanProviderId || !cleanModelId) {
    return
  }

  const value = `${cleanProviderId}::${cleanModelId}`
  if (choices.has(value)) {
    return
  }

  choices.set(value, {
    value,
    providerId: cleanProviderId,
    modelId: cleanModelId,
    label: `${providerName?.trim() || cleanProviderId} / ${cleanModelId}`,
    capabilities: [...capabilities],
  })
}
