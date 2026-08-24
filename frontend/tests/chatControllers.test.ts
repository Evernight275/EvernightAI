import { describe, expect, it } from 'vitest'
import { prerequisiteNotice } from '../src/components/chat/chatPrerequisites'
import { canSubmitChat } from '../src/components/chat/chatRequestForm'
import { approvalItem, formatChatError } from '../src/components/chat/chatRequestStatus'
import {
  isChatRunCancelable,
  isChatSubmissionBlocked,
} from '../src/components/chat/chatView'
import { sidebarItems } from '../src/components/chat/chatSidebar'

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
      sessionReady: false,
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

  it('blocks new messages while an approval or paused run needs attention', () => {
    expect(isChatSubmissionBlocked('approvalRequired', null)).toBe(true)
    expect(isChatSubmissionBlocked('resumeRequired', null)).toBe(true)
    expect(isChatSubmissionBlocked('idle', null)).toBe(false)
    expect(isChatSubmissionBlocked('failed', {
      run_id: 'run-paused',
      request: {
        provider_id: 'main',
        context_id: 'context-1',
        model_id: 'model-1',
      },
      status: 'paused',
    })).toBe(true)
    expect(isChatSubmissionBlocked('failed', null, 'run-unknown')).toBe(true)
    expect(isChatRunCancelable('failed', null, 'run-unknown')).toBe(true)
  })

  it('presents approval arguments, permissions, and the current decision', () => {
    expect(approvalItem({
      approval_id: 'approval-1',
      tool_call_id: 'call-1',
      tool_name: 'write_file',
      tool_call: { name: 'write_file', arguments: { path: 'note.txt' } },
      permissions: ['filesystem', 'write'],
    }, 'approved')).toMatchObject({
      permissionsText: 'filesystem, write',
      decisionText: '已批准',
      toolCallText: expect.stringContaining('note.txt'),
    })
  })

  it('orders sidebar sessions and marks the current context', () => {
    expect(sidebarItems([
      {
        session_id: 'older',
        context_id: 'context-1',
        created_at: '2026-08-20T00:00:00.000Z',
      },
      {
        session_id: 'newer',
        title: 'Recent work',
        context_id: 'context-2',
        updated_at: '2026-08-24T00:00:00.000Z',
        status: 'archived',
      },
    ], {
      session_id: 'older',
      context_id: 'context-1',
    })).toEqual([
      {
        id: 'older',
        title: 'older',
        status: 'active',
        active: true,
      },
      {
        id: 'newer',
        title: 'Recent work',
        status: 'archived',
        active: false,
      },
    ])
  })
})
