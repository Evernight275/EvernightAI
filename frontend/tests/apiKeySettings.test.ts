import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getIdentity } from '../src/api/auth'
vi.mock('../src/api/auth', () => ({ getIdentity: vi.fn() }))
import { useApiKeySettings } from '../src/components/settings/apiKeySettings'

describe('API Key settings controller', () => {
  beforeEach(() => {
    vi.mocked(getIdentity).mockReset().mockResolvedValue({ authentication_enabled: true, principal: { principal_id: 'user-1', principal_type: 'user', roles: [], permissions: [] } })
    vi.stubGlobal('localStorage', new MemoryStorage())
    vi.stubGlobal('window', {
      EVERNIGHTAI_API_KEY: '',
      dispatchEvent: vi.fn(),
    })
  })

  it('saves a normalized API Key and reports the credential change', async () => {
    const settings = useApiKeySettings()

    settings.edit('  api-key  ')
    await settings.save()

    expect(localStorage.getItem('evernight.apiKey')).toBe('api-key')
    expect(settings.apiKey.value).toBe('api-key')
    expect(settings.changed.value).toBe(false)
    expect(settings.feedback.value).toBe('身份已验证，访问凭证已保存。')
    expect(window.dispatchEvent).toHaveBeenCalledOnce()
  })

  it('retains the old credential when validation fails', async () => {
    localStorage.setItem('evernight.apiKey', 'old-key')
    vi.mocked(getIdentity).mockRejectedValue(new Error('Invalid credential'))
    const settings = useApiKeySettings()
    settings.edit('bad-key')
    await settings.save()
    expect(localStorage.getItem('evernight.apiKey')).toBe('old-key')
    expect(settings.error.value).toBe('Invalid credential')
    expect(window.dispatchEvent).not.toHaveBeenCalled()
  })

  it('does not persist credentials against an unsecured server', async () => {
    vi.mocked(getIdentity).mockResolvedValue({ authentication_enabled: false, principal: null })
    const settings = useApiKeySettings()
    settings.edit('unverified-key')
    await settings.save()
    expect(localStorage.getItem('evernight.apiKey')).toBeNull()
  })

  it('clears a stored API Key', () => {
    localStorage.setItem('evernight.apiKey', 'api-key')
    const settings = useApiKeySettings()

    settings.clear()

    expect(localStorage.getItem('evernight.apiKey')).toBeNull()
    expect(settings.apiKey.value).toBe('')
    expect(settings.feedback.value).toBe('已退出此浏览器，并清除保存的访问凭证。')
  })

  it('disables page-provided credentials on sign out', () => {
    window.EVERNIGHTAI_API_KEY = 'page-key'
    localStorage.setItem('evernight.apiKey', 'local-key')
    const settings = useApiKeySettings()

    settings.clear()

    expect(settings.apiKey.value).toBe('')
    expect(settings.feedback.value).toBe('已退出此浏览器，并清除保存的访问凭证。')
  })
})

class MemoryStorage implements Storage {
  private readonly values = new Map<string, string>()

  get length(): number {
    return this.values.size
  }

  clear(): void {
    this.values.clear()
  }

  getItem(key: string): string | null {
    return this.values.get(key) ?? null
  }

  key(index: number): string | null {
    return [...this.values.keys()][index] ?? null
  }

  removeItem(key: string): void {
    this.values.delete(key)
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value)
  }
}
