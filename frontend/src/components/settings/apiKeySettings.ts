import { computed, ref } from 'vue'
import { getApiKey, setApiKey } from '../../api/client'

export function useApiKeySettings() {
  const persistedApiKey = ref(getApiKey())
  const apiKey = ref(persistedApiKey.value)
  const revealed = ref(false)
  const feedback = ref<string | null>(null)

  const inputType = computed(() => revealed.value ? 'text' : 'password')
  const revealLabel = computed(() => revealed.value ? '隐藏' : '显示')
  const changed = computed(() => apiKey.value.trim() !== persistedApiKey.value)
  const canClear = computed(() => Boolean(apiKey.value || persistedApiKey.value))

  function edit(value: string): void {
    apiKey.value = value
    feedback.value = null
  }

  function handleInput(event: Event): void {
    edit((event.target as HTMLInputElement).value)
  }

  function toggleReveal(): void {
    revealed.value = !revealed.value
  }

  function save(): void {
    setApiKey(apiKey.value)
    persistedApiKey.value = getApiKey()
    apiKey.value = persistedApiKey.value
    feedback.value = persistedApiKey.value ? 'API Key 已保存。' : 'API Key 已清除。'
  }

  function clear(): void {
    setApiKey('')
    persistedApiKey.value = getApiKey()
    apiKey.value = persistedApiKey.value
    feedback.value = persistedApiKey.value
      ? '已恢复页面预设的 API Key。'
      : 'API Key 已清除。'
  }

  return {
    apiKey,
    inputType,
    revealed,
    revealLabel,
    changed,
    canClear,
    feedback,
    edit,
    handleInput,
    toggleReveal,
    save,
    clear,
  }
}
