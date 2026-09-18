import { computed, ref } from 'vue'
import { getIdentity, type AuthSession } from '../../api/auth'
import { getAccessToken, getApiKey, setAccessToken, setApiKey, signOut } from '../../api/client'

export function useApiKeySettings() {
  const kind = ref<'api-key' | 'bearer'>(getAccessToken() ? 'bearer' : 'api-key')
  const persistedApiKey = ref(getAccessToken() || getApiKey())
  const apiKey = ref(persistedApiKey.value)
  const revealed = ref(false)
  const feedback = ref<string | null>(null)
  const error = ref<string | null>(null)
  const busy = ref(false)
  const identity = ref<AuthSession | null>(null)
  const inputType = computed(() => revealed.value ? 'text' : 'password')
  const revealLabel = computed(() => revealed.value ? '隐藏' : '显示')
  const changed = computed(() => apiKey.value.trim() !== persistedApiKey.value)
  const canClear = computed(() => Boolean(apiKey.value || getApiKey() || getAccessToken()))

  function edit(value: string): void {
    apiKey.value = value
    feedback.value = null
    error.value = null
  }
  function handleInput(event: Event): void {
    edit((event.target as HTMLInputElement).value)
  }
  function toggleReveal(): void { revealed.value = !revealed.value }

  async function save(): Promise<void> {
    if (busy.value || !apiKey.value.trim()) return
    busy.value = true
    error.value = null
    feedback.value = null
    const credential = { kind: kind.value, value: apiKey.value.trim() }
    try {
      const session = await getIdentity(credential)
      identity.value = session
      if (!session.authentication_enabled || !session.principal) {
        feedback.value = '服务未启用认证，无需保存凭证。'
        return
      }
      if (credential.kind === 'bearer') setAccessToken(credential.value)
      else setApiKey(credential.value)
      persistedApiKey.value = credential.value
      apiKey.value = credential.value
      revealed.value = false
      feedback.value = '身份已验证，访问凭证已保存。'
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '身份验证失败，请重试。'
    } finally { busy.value = false }
  }

  async function refreshIdentity(): Promise<void> {
    if (busy.value) return
    busy.value = true
    error.value = null
    try { identity.value = await getIdentity() }
    catch (cause) {
      identity.value = null
      error.value = cause instanceof Error ? cause.message : '无法读取身份。'
    } finally { busy.value = false }
  }

  function clear(): void {
    if (busy.value) return
    signOut()
    persistedApiKey.value = ''
    apiKey.value = ''
    identity.value = null
    revealed.value = false
    error.value = null
    feedback.value = '已退出此浏览器，并清除保存的访问凭证。'
  }
  return { kind, apiKey, inputType, revealed, revealLabel, changed, canClear, feedback,
    error, busy, identity, edit, handleInput, toggleReveal, save, clear, refreshIdentity }
}
