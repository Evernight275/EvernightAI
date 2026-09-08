import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import ChatApp from '../src/ChatApp.vue'
import ChatMessage from '../src/components/chat/ChatMessage.vue'
import ChatRequestForm from '../src/components/chat/ChatRequestForm.vue'
import ChatRequestStatus from '../src/components/chat/ChatRequestStatus.vue'
import ChatRunDetails from '../src/components/chat/ChatRunDetails.vue'
import ChatToolActivity from '../src/components/chat/ChatToolActivity.vue'
import ChatView from '../src/components/chat/ChatView.vue'

describe('chat component composition', () => {
  it('composes session management beside the chat page', async () => {
    const html = await renderToString(createSSRApp(ChatApp))

    expect(html).toContain('class="chat-layout"')
    expect(html).toContain('class="chat-sidebar"')
    expect(html).toContain('aria-label="会话管理"')
    expect(html).toContain('新建会话')
    expect(html).toContain('没有会话')
    expect(html).toContain('设置')
    expect(html).toContain('class="chat-main"')
    expect(html).toContain('class="chat-view-header"')
    expect(html).toContain('class="chat-view-scroll"')
    expect(html).toContain('class="chat-view-footer"')
    expect(html).toContain('EvernightAI')
    expect(html).toContain('今天想聊些什么？')
  })

  it('delegates the chat skeleton and its empty state', async () => {
    const html = await renderToString(createSSRApp(ChatView))

    expect(html).toContain('发送消息')
    expect(html).toContain('运行详情')
    expect(html).toContain('前置状态')
    expect(html).toContain('请求状态')
    expect(html).toContain('工具调用（0）')
    expect(html).toContain('Tools：0')
    expect(html).toContain('aria-label="对话记录"')
    expect(html).toContain('还没有消息')
    expect(html).not.toContain('<datalist')

    expect(html.indexOf('class="chat-transcript"')).toBeLessThan(
      html.indexOf('class="chat-composer"'),
    )
    expect(html.indexOf('class="chat-details-panel"')).toBeGreaterThan(
      html.indexOf('class="chat-composer"'),
    )
    const header = html.slice(html.indexOf('<header'), html.indexOf('</header>'))
    expect(header).toContain('准备就绪')
    expect(header).not.toContain('前置状态')
    expect(header).not.toContain('<dialog')
    expect(html.indexOf('class="chat-request-status"')).toBeGreaterThan(html.indexOf('class="chat-view-footer"'))
    expect(html.indexOf('class="chat-request-status"')).toBeLessThan(html.indexOf('class="chat-composer"'))
    expect(html.indexOf('class="chat-composer-message"')).toBeLessThan(
      html.indexOf('class="chat-composer-options"'),
    )
  })

  it('renders a focused user or assistant message component', async () => {
    const html = await renderToString(createSSRApp(ChatMessage, {
      entry: {
        entryId: 'assistant-1',
        role: 'assistant',
        text: 'A direct answer.',
        modelId: 'model-1',
        content: {
          role: 'assistant',
          content: [{ type: 'text', text: 'A direct answer.' }],
        },
      },
    }))

    expect(html).toContain('class="chat-message chat-message--assistant"')
    expect(html).toContain('EvernightAI')
    expect(html).toContain('A direct answer.')
    expect(html).not.toContain('model-1')
  })

  it('selects models from the active Provider catalog', async () => {
    const html = await renderToString(createSSRApp(ChatRequestForm, {
      catalog: {
        providers: [{
          provider_id: 'main',
          name: 'Main',
          type: 'openai',
        }],
        modelGroups: [{
          provider: {
            provider_id: 'main',
            name: 'Main',
            type: 'openai',
          },
          models: [{ model_id: 'model-1' }, { model_id: 'model-2' }],
        }],
      },
      busy: false,
      sessionReady: true,
    }))

    expect(html).toContain('aria-label="选择模型"')
    expect(html).toContain('aria-pressed="true"')
    expect(html).toContain('model-1')
    expect(html).toContain('model-2')
    expect(html).toContain('aria-label="搜索模型"')
    expect(html).not.toContain('<select')
  })

  it('keeps approval decisions visible before large tool arguments', async () => {
    const html = await renderToString(createSSRApp(ChatRequestStatus, {
      state: 'approvalRequired',
      error: null,
      pendingApprovals: [{
        approval_id: 'approval-1',
        tool_call_id: 'call-1',
        tool_name: 'write_text_file',
        safety_level: 'sensitive',
        permissions: ['write', 'filesystem'],
        tool_call: {
          name: 'write_text_file',
          arguments: { path: 'large.py', content: 'line\n'.repeat(500) },
        },
      }],
      approvalStatuses: {},
    }))

    expect(html).toContain('class="chat-tool-approval"')
    expect(html).toContain('class="chat-approval-payload"')
    expect(html).toContain('查看调用参数')
    expect(html.indexOf('批准')).toBeLessThan(html.indexOf('查看调用参数'))
    expect(html.indexOf('拒绝')).toBeLessThan(html.indexOf('查看调用参数'))
    expect(html.indexOf('large.py')).toBeLessThan(html.indexOf('查看调用参数'))
    expect(html).not.toContain('运行 ID')
  })

  it('shows pending approvals in the tool activity count', async () => {
    const html = await renderToString(createSSRApp(ChatToolActivity, {
      run: null,
      trace: [],
      pendingApprovals: [{
        approval_id: 'approval-1',
        tool_call_id: 'call-1',
        tool_name: 'write_text_file',
      }],
    }))

    expect(html).toContain('工具调用（1）')
    expect(html).toContain('write_text_file / 等待审批')
    expect(html).not.toContain('还没有工具调用')
  })

  it('keeps an idle attention area empty and shows recovery actions near errors', async () => {
    const props = { state: 'idle', error: null, pendingApprovals: [], approvalStatuses: {} }
    const idle = await renderToString(createSSRApp(ChatRequestStatus, props))
    const failed = await renderToString(createSSRApp(ChatRequestStatus, {
      ...props, state: 'failed', error: new Error('Provider unavailable'),
    }))
    const paused = await renderToString(createSSRApp(ChatRequestStatus, { ...props, state: 'resumeRequired' }))
    expect(idle).not.toContain('chat-request-status')
    expect(failed).toContain('role="alert"')
    expect(failed).toContain('Provider unavailable')
    expect(failed).toContain('重试')
    expect(failed).toContain('查看详情')
    expect(paused).toContain('继续运行')
  })

  it('places stop in the composer instead of a disabled send button', async () => {
    const html = await renderToString(createSSRApp(ChatRequestForm, {
      catalog: { providers: [], modelGroups: [] }, busy: true,
      sessionReady: true, canStop: true, state: 'approvalRequired',
    }))
    expect(html).toContain('aria-label="停止当前运行"')
    expect(html).not.toContain('type="submit"')
    expect(html).not.toContain('发送中')
  })

  it('keeps diagnostics in a separate dialog without duplicate approval actions', async () => {
    const html = await renderToString(createSSRApp(ChatRunDetails, {
      open: false, workspaceState: 'ready', chatState: 'approvalRequired',
      workspaceIssues: [], providerCount: 1, toolCount: 1,
      error: null, hasTranscript: true, busy: true, run: null, trace: [], runId: 'run-1',
      pendingApprovals: [{ approval_id: 'approval-1', tool_call_id: 'call-1', tool_name: 'write_file' }],
    }))
    expect(html).toContain('<dialog')
    expect(html).toContain('运行 ID')
    expect(html).toContain('原始请求参数')
    expect(html).toContain('诊断信息')
    expect(html).not.toContain('class="chat-approval-actions"')
    expect(html).toContain('disabled')
  })
})
