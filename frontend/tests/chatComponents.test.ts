import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import ChatApp from '../src/ChatApp.vue'
import ChatView from '../src/components/chat/ChatView.vue'

describe('chat component composition', () => {
  it('composes session management beside the chat page', async () => {
    const html = await renderToString(createSSRApp(ChatApp))

    expect(html).toContain('class="chat-layout"')
    expect(html).toContain('class="chat-sidebar"')
    expect(html).toContain('aria-label="会话管理"')
    expect(html).toContain('新建会话')
    expect(html).toContain('没有会话')
    expect(html).toContain('>设置</a>')
    expect(html).toContain('class="chat-main"')
    expect(html).toContain('EvernightAI Chat')
  })

  it('delegates the chat skeleton and its empty state', async () => {
    const html = await renderToString(createSSRApp(ChatView))

    expect(html).toContain('前置状态')
    expect(html).toContain('Tools：0')
    expect(html).toContain('发送消息')
    expect(html).toContain('请求状态')
    expect(html).toContain('工具调用（0）')
    expect(html).toContain('本地对话记录（0）')
    expect(html).toContain('还没有消息')
    expect(html).not.toContain('<datalist')
  })
})
