import { computed, ref, watch } from 'vue'
import type { ChatSubmission } from '../../domain/chat'
import type { ProviderCatalog } from '../../domain/workspace'

export type ChatRequestFormProps = {
  catalog: ProviderCatalog
  busy: boolean
  sessionReady: boolean
  defaultProviderId?: string | null
  defaultModelId?: string | null
}

export type ChatRequestFormEmits = {
  submit: [submission: ChatSubmission]
}

type ChatRequestFormEmit = (
  event: 'submit',
  submission: ChatSubmission,
) => void

export function useChatRequestForm(
  props: ChatRequestFormProps,
  emit: ChatRequestFormEmit,
) {
  const providerId = ref('')
  const modelId = ref('')
  const text = ref('')

  const models = computed(() => props.catalog.modelGroups.find(
    (group) => group.provider.provider_id === providerId.value,
  )?.models || [])

  const canSubmit = computed(() => canSubmitChat({
    busy: props.busy,
    sessionReady: props.sessionReady,
    providerId: providerId.value,
    modelId: modelId.value,
    text: text.value,
  }))

  watch(
    () => props.catalog.providers,
    (providers) => {
      if (!providers.some((provider) => provider.provider_id === providerId.value)) {
        providerId.value = providers[0]?.provider_id || ''
      }
    },
    { immediate: true },
  )

  watch(providerId, () => {
    modelId.value = models.value[0]?.model_id || ''
  })

  watch(
    [
      () => props.defaultProviderId,
      () => props.defaultModelId,
      () => props.catalog.providers,
    ],
    ([defaultProviderId, defaultModelId]) => {
      if (!defaultProviderId || !props.catalog.providers.some(
        (provider) => provider.provider_id === defaultProviderId,
      )) {
        return
      }
      providerId.value = defaultProviderId
      modelId.value = defaultModelId?.trim()
        || models.value[0]?.model_id
        || ''
    },
    { immediate: true, flush: 'sync' },
  )

  function submit(): void {
    if (!canSubmit.value) {
      return
    }

    emit('submit', {
      providerId: providerId.value,
      modelId: modelId.value.trim(),
      text: text.value.trim(),
    })
    text.value = ''
  }

  return {
    providerId,
    modelId,
    text,
    canSubmit,
    providerDisabled: computed(() => (
      props.busy || !props.sessionReady || props.catalog.providers.length === 0
    )),
    modelDisabled: computed(() => (
      props.busy || !props.sessionReady || providerId.value === ''
    )),
    messageDisabled: computed(() => props.busy || !props.sessionReady),
    submitLabel: computed(() => !props.sessionReady
      ? '请先选择会话'
      : props.busy ? '发送中' : '发送'),
    submit,
  }
}

export function canSubmitChat(values: {
  busy: boolean
  sessionReady?: boolean
  providerId: string
  modelId: string
  text: string
}): boolean {
  return !values.busy
    && values.sessionReady !== false
    && values.providerId !== ''
    && values.modelId.trim() !== ''
    && values.text.trim() !== ''
}
