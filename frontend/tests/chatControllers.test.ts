import { describe, expect, it } from 'vitest'
import { chatHeaderTitle } from '../src/components/chat/chatHeader'
import { chatMessagePresentation } from '../src/components/chat/chatMessage'
import { prerequisiteNotice } from '../src/components/chat/chatPrerequisites'
import {
  canSubmitChat,
  shouldSubmitChatKeydown,
} from '../src/components/chat/chatRequestForm'
import {
  approvalItem,
  formatChatError,
  formatChatState,
} from '../src/components/chat/chatRequestStatus'
import { toolActivities } from '../src/components/chat/chatToolActivity'
import {
  isChatRunCancelable,
  isChatSubmissionBlocked,
} from '../src/components/chat/chatView'
import { sidebarItems } from '../src/components/chat/chatSidebar'
import { transcriptFromMessages } from '../src/domain/chat'

describe('chat component controllers', () => {
  it('derives chat header and message presentation outside Vue', () => {
    expect(chatHeaderTitle(null)).toBe('EvernightAI')
    expect(chatHeaderTitle({
      session_id: 'session-1',
      context_id: 'context-1',
      title: 'Planning',
    })).toBe('Planning')
    expect(chatMessagePresentation({
      entryId: 'user-1',
      role: 'user',
      text: 'hello',
      modelId: 'model-1',
      content: { role: 'user' },
    })).toEqual({
      roleLabel: '你',
      roleClass: 'user',
      markdown: false,
    })
  })

  it('keeps only visible user and assistant text in the conversation', () => {
    expect(transcriptFromMessages([
      { role: 'system', content: [{ type: 'text', text: 'instruction' }] },
      { role: 'user', content: [{ type: 'text', text: 'question' }] },
      { role: 'assistant', tool_calls: [{
        tool_call_id: 'call-1',
        tool_call: { name: 'read_file' },
      }] },
      { role: 'tool', content: [{ type: 'text', text: 'tool output' }] },
      { role: 'assistant', content: [{ type: 'text', text: 'answer' }] },
    ]).map((entry) => [entry.role, entry.text])).toEqual([
      ['user', 'question'],
      ['assistant', 'answer'],
    ])
  })

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

  it('submits with Enter while preserving Shift+Enter and composition', () => {
    expect(shouldSubmitChatKeydown({
      key: 'Enter',
      shiftKey: false,
      isComposing: false,
    })).toBe(true)
    expect(shouldSubmitChatKeydown({
      key: 'Enter',
      shiftKey: true,
      isComposing: false,
    })).toBe(false)
    expect(shouldSubmitChatKeydown({
      key: 'Enter',
      shiftKey: false,
      isComposing: true,
    })).toBe(false)
  })

  it('formats request errors outside the Vue component', () => {
    expect(formatChatError(new Error('provider unavailable'))).toBe('provider unavailable')
    expect(formatChatError('request failed')).toBe('request failed')
    expect(formatChatError(null)).toBeNull()
  })

  it('presents internal chat states as readable labels', () => {
    expect(formatChatState('approvalRequired')).toBe('等待工具审批')
    expect(formatChatState('streaming')).toBe('正在生成回复')
    expect(formatChatState('customState')).toBe('customState')
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

  it('offers stop only in states that can accept cancellation', () => {
    for (const state of ['preparing', 'streaming', 'approvalRequired', 'resumeRequired', 'resuming', 'retrying']) {
      expect(isChatRunCancelable(state, null, 'run-1')).toBe(true)
    }
    for (const state of ['idle', 'canceled', 'canceling', 'clearing', 'creatingSession', 'loadingSession']) {
      expect(isChatRunCancelable(state, null, 'run-1')).toBe(false)
    }
    expect(isChatRunCancelable('failed', null, null)).toBe(false)
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
      safetyLabel: '风险未知',
      targets: [{ name: '路径', value: 'note.txt' }],
    })
  })

  it('counts a pending approval as tool activity', () => {
    expect(toolActivities(null, [], [{
      approval_id: 'approval-1',
      tool_call_id: 'call-1',
      tool_name: 'write_text_file',
      safety_level: 'sensitive',
    }])).toEqual([{
      key: 'call-1',
      name: 'write_text_file',
      status: 'approval required',
      statusLabel: '等待审批',
      callText: '{}',
      resultText: null,
    }])
  })

  it('orders sidebar sessions and marks the current context', () => {
    expect(sidebarItems([
      {
        session_id: 'older',
        context_id: 'context-1',
        created_at: '2026-08-20T00:00:00.000Z',
        updated_at: '2026-08-25T00:00:00.000Z',
      },
      {
        session_id: 'newer',
        title: 'Recent work',
        context_id: 'context-2',
        created_at: '2026-08-24T00:00:00.000Z',
        status: 'archived',
      },
    ], {
      session_id: 'older',
      context_id: 'context-1',
    })).toEqual([
      {
        id: 'newer',
        title: 'Recent work',
        status: 'archived',
        active: false,
      },
      {
        id: 'older',
        title: 'older',
        status: 'active',
        active: true,
      },
    ])
  })
})
