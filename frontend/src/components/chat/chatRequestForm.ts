import { computed, ref, watch, type ComponentPublicInstance } from 'vue'
import type { ChatSubmission } from '../../domain/chat'
import type { ProviderCatalog } from '../../domain/workspace'
import { formatChatState } from './chatRequestStatus'

export type ChatRequestFormProps = {
  catalog: ProviderCatalog
  busy: boolean
  sessionReady: boolean
  state?: string
  canStop?: boolean
  defaultProviderId?: string | null
  defaultModelId?: string | null
}

export type ChatRequestFormEmits = {
  submit: [submission: ChatSubmission]
  cancel: []
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
  const textarea = ref<HTMLTextAreaElement | null>(null)
  watch([text, textarea], () => {
    if (!textarea.value) return
    textarea.value.style.height = 'auto'
    textarea.value.style.height = `${textarea.value.scrollHeight}px`
  }, { flush: 'post' })

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

  watch(models, (availableModels) => {
    if (!availableModels.some((model) => model.model_id === modelId.value)) {
      modelId.value = availableModels[0]?.model_id || ''
    }
  }, { immediate: true, flush: 'sync' })

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

  function handleMessageKeydown(event: KeyboardEvent): void {
    if (!shouldSubmitChatKeydown(event)) {
      return
    }
    event.preventDefault()
    submit()
  }

  return {
    setTextarea(element: Element | ComponentPublicInstance | null): void {
      textarea.value = element as HTMLTextAreaElement | null
    },
    providerId,
    modelId,
    models,
    text,
    canSubmit,
    providerDisabled: computed(() => (
      props.busy || !props.sessionReady || props.catalog.providers.length === 0
    )),
    modelDisabled: computed(() => (
      props.busy
      || !props.sessionReady
      || providerId.value === ''
      || models.value.length === 0
    )),
    messageDisabled: computed(() => props.busy || !props.sessionReady),
    submitLabel: computed(() => !props.sessionReady
      ? '请先选择会话'
      : props.busy ? formatChatState(props.state || 'streaming') : '发送'),
    handleMessageKeydown,
    submit,
  }
}

export function shouldSubmitChatKeydown(event: Pick<
  KeyboardEvent,
  'key' | 'shiftKey' | 'isComposing'
>): boolean {
  return event.key === 'Enter' && !event.shiftKey && !event.isComposing
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
