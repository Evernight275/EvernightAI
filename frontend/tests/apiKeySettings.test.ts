import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useApiKeySettings } from '../src/components/settings/apiKeySettings'

describe('API Key settings controller', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', new MemoryStorage())
    vi.stubGlobal('window', {
      EVERNIGHTAI_API_KEY: '',
      dispatchEvent: vi.fn(),
    })
  })

  it('saves a normalized API Key and reports the credential change', () => {
    const settings = useApiKeySettings()

    settings.edit('  api-key  ')
    settings.save()

    expect(localStorage.getItem('evernight.apiKey')).toBe('api-key')
    expect(settings.apiKey.value).toBe('api-key')
    expect(settings.changed.value).toBe(false)
    expect(settings.feedback.value).toBe('API Key 已保存。')
    expect(window.dispatchEvent).toHaveBeenCalledOnce()
  })

  it('clears a stored API Key', () => {
    localStorage.setItem('evernight.apiKey', 'api-key')
    const settings = useApiKeySettings()

    settings.clear()

    expect(localStorage.getItem('evernight.apiKey')).toBeNull()
    expect(settings.apiKey.value).toBe('')
    expect(settings.feedback.value).toBe('API Key 已清除。')
  })

  it('keeps a page-provided API Key when local credentials are cleared', () => {
    window.EVERNIGHTAI_API_KEY = 'page-key'
    localStorage.setItem('evernight.apiKey', 'local-key')
    const settings = useApiKeySettings()

    settings.clear()

    expect(settings.apiKey.value).toBe('page-key')
    expect(settings.feedback.value).toBe('已恢复页面预设的 API Key。')
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
