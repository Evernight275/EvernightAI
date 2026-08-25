import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import ChatApp from '../src/ChatApp.vue'
import ChatRequestForm from '../src/components/chat/ChatRequestForm.vue'
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
    expect(html).toContain('class="chat-view-header"')
    expect(html).toContain('class="chat-view-scroll"')
    expect(html).toContain('class="chat-view-footer"')
    expect(html).toContain('EvernightAI Chat')
  })

  it('delegates the chat skeleton and its empty state', async () => {
    const html = await renderToString(createSSRApp(ChatView))

    expect(html).toContain('发送消息')
    expect(html).toContain('运行详情')
    expect(html).toContain('前置状态')
    expect(html).toContain('请求状态')
    expect(html).toContain('工具调用（0）')
    expect(html).toContain('Tools：0')
    expect(html).toContain('本地对话记录（0）')
    expect(html).toContain('还没有消息')
    expect(html).not.toContain('<datalist')

    expect(html.indexOf('class="chat-transcript"')).toBeLessThan(
      html.indexOf('class="chat-composer"'),
    )
    expect(html.indexOf('class="chat-details"')).toBeLessThan(
      html.indexOf('class="chat-transcript"'),
    )
    expect(html.indexOf('class="chat-composer-message"')).toBeLessThan(
      html.indexOf('class="chat-composer-options"'),
    )
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

    expect(html).toContain('<option value="model-1" selected>model-1</option>')
    expect(html).toContain('<option value="model-2">model-2</option>')
    expect(html).not.toContain('<input')
  })
})
