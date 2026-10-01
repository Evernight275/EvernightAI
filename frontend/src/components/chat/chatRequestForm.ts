import { workingDirectory } from '../../runtime/workingDirectory'
import { computed, onUnmounted, ref, watch, type ComponentPublicInstance } from 'vue'
import type { ChatSubmission } from '../../domain/chat'
import type { ProviderCatalog } from '../../domain/workspace'
import { formatChatState } from './chatRequestStatus'
import { composeContextPreview, type SkillDefinition, type ToolDefinition } from '../../api'
import { parseSkillVariables } from '../../domain/skillParameters'

export type ChatRequestFormProps = {
  skills?: SkillDefinition[]
  contextId?: string | null
  sessionId?: string | null
  tools?: ToolDefinition[]
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
  const selectedSkill = ref('')
  const skillVariables = ref('{}')
  const optionsError = ref('')
  const preview = ref('')
  const previewing = ref(false)
  let previewGeneration = 0
  const availableSkills = computed(() => (props.skills || []).filter(skill => skill.is_enabled !== false && skill.capabilities?.includes('agent')))
  const currentSkill = computed(() => props.skills?.find(skill => skill.name === selectedSkill.value))
  const missingSkillTools = computed(() => (currentSkill.value?.required_tools || []).filter(name => !props.tools?.some(tool => tool.name === name)))
  const skillUnavailable = computed(() => !!selectedSkill.value && (!availableSkills.value.some(skill => skill.name === selectedSkill.value) || missingSkillTools.value.length > 0))
  watch(selectedSkill, () => { skillVariables.value = '{}'; preview.value = ''; optionsError.value = '' })
  watch(skillVariables, () => { preview.value = ''; optionsError.value = '' })
  watch([selectedSkill, skillVariables, modelId, text, () => props.contextId, () => props.skills, () => props.tools], () => {
    previewGeneration++; preview.value = ''; previewing.value = false
  })
  onUnmounted(() => previewGeneration++)
  function currentSkills() {
    if (!selectedSkill.value) return undefined
    if (skillUnavailable.value) throw new Error('当前技能不可用或缺少必需工具')
    return [{ skill_name: selectedSkill.value, variables: parseSkillVariables(skillVariables.value) }]
  }
  async function previewContext() {
    if (!props.contextId || previewing.value) return
    const current = ++previewGeneration
    previewing.value = true; optionsError.value = ''; preview.value = ''
    try {
      const response = await composeContextPreview(props.contextId, {
      model_id: modelId.value, messages: [{ role: 'user', content: [{ type: 'text', text: text.value.trim() }] }],
      skills: currentSkills(), tools: props.tools,
      metadata: props.sessionId ? { session_id: props.sessionId } : {},
      })
      if (current === previewGeneration) preview.value = JSON.stringify(response, null, 2)
    } catch (cause) { if (current === previewGeneration) optionsError.value = cause instanceof Error ? cause.message : '预览失败' }
    finally { if (current === previewGeneration) previewing.value = false }
  }
  const textarea = ref<HTMLTextAreaElement | null>(null)
  watch([text, textarea], () => {
    if (!textarea.value) return
    textarea.value.style.height = 'auto'
    textarea.value.style.height = `${textarea.value.scrollHeight}px`
  }, { flush: 'post' })

  const enabledProviders = computed(() => props.catalog.providers.filter((provider) => provider.is_enabled !== false))
  const selectedProviderDisabled = computed(() => props.catalog.providers.some(
    (provider) => provider.provider_id === providerId.value && provider.is_enabled === false,
  ))
  const models = computed(() => props.catalog.modelGroups.find(
    (group) => group.provider.provider_id === providerId.value,
  )?.models || [])

  const canSubmit = computed(() => enabledProviders.value.some(
    (provider) => provider.provider_id === providerId.value,
  ) && !skillUnavailable.value && canSubmitChat({
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
        providerId.value = enabledProviders.value[0]?.provider_id || ''
      }
    },
    { immediate: true },
  )

  watch([providerId, models], ([selectedProvider, availableModels], [previousProvider, previousModels]) => {
    if (selectedProviderDisabled.value) return
    const removedDeclaredModel = previousModels?.some((model) => model.model_id === modelId.value)
      && !availableModels.some((model) => model.model_id === modelId.value)
    if (selectedProvider !== previousProvider || !modelId.value || removedDeclaredModel) {
      modelId.value = availableModels[0]?.model_id || ''
    }
  }, { immediate: true, flush: 'sync' })

  let appliedDefaults = ''
  watch(
    [
      () => props.defaultProviderId,
      () => props.defaultModelId,
      () => props.sessionId,
      () => props.catalog.providers,
    ],
    ([defaultProviderId, defaultModelId, sessionId]) => {
      if (!defaultProviderId) { appliedDefaults = ''; return }
      if (!props.catalog.providers.some(
        (provider) => provider.provider_id === defaultProviderId,
      )) {
        return
      }
      const defaults = JSON.stringify([sessionId, defaultProviderId, defaultModelId])
      if (appliedDefaults === defaults) return
      appliedDefaults = defaults
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

    optionsError.value = ''
    let skills
    try { skills = currentSkills() } catch (cause) { optionsError.value = cause instanceof Error ? cause.message : '技能参数无效'; return }
    emit('submit', {
      workingDirectory: workingDirectory.value,
      providerId: providerId.value,
      modelId: modelId.value.trim(),
      text: text.value.trim(),
      ...(skills ? { skills } : {}),
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
    availableSkills, currentSkill, missingSkillTools, skillUnavailable,
    selectedSkill, skillVariables, optionsError, preview, previewing, previewContext,
    setTextarea(element: Element | ComponentPublicInstance | null): void {
      textarea.value = element as HTMLTextAreaElement | null
    },
    providerId,
    modelId,
    models,
    text,
    canSubmit,
    selectedProviderDisabled,
    providerDisabled: computed(() => (
      props.busy || !props.sessionReady || enabledProviders.value.length === 0
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
