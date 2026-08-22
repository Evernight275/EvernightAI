import { describe, expect, it } from 'vitest'
import { prerequisiteNotice } from '../src/components/chat/chatPrerequisites'
import { canSubmitChat } from '../src/components/chat/chatRequestForm'
import { formatChatError } from '../src/components/chat/chatRequestStatus'

describe('chat component controllers', () => {
  it('derives prerequisite notices outside the Vue component', () => {
    expect(prerequisiteNotice('loading', 0)).toBe('正在读取 Provider。')
    expect(prerequisiteNotice('offline', 0)).toBe('后端不可用。')
    expect(prerequisiteNotice('unauthorized', 0)).toBe('业务接口需要认证。')
    expect(prerequisiteNotice('ready', 0)).toBe('没有可用 Provider。')
    expect(prerequisiteNotice('ready', 1)).toBeNull()
  })

  it('validates submissions outside the Vue component', () => {
    expect(canSubmitChat({
      busy: false,
      providerId: 'main',
      modelId: 'model-1',
      text: 'hello',
    })).toBe(true)
    expect(canSubmitChat({
      busy: true,
      providerId: 'main',
      modelId: 'model-1',
      text: 'hello',
    })).toBe(false)
    expect(canSubmitChat({
      busy: false,
      providerId: 'main',
      modelId: ' ',
      text: 'hello',
    })).toBe(false)
  })

  it('formats request errors outside the Vue component', () => {
    expect(formatChatError(new Error('provider unavailable'))).toBe('provider unavailable')
    expect(formatChatError('request failed')).toBe('request failed')
    expect(formatChatError(null)).toBeNull()
  })
})
