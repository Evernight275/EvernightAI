import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ApiKeySettings from '../src/components/settings/ApiKeySettings.vue'
import WorkspaceContents from '../src/components/workspace/WorkspaceContents.vue'
import { emptyWorkspaceSnapshot } from '../src/domain/workspace'

describe('workspace component composition', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', {
      getItem: vi.fn().mockReturnValue(null),
    })
    vi.stubGlobal('window', {
      EVERNIGHTAI_API_KEY: '',
    })
  })

  it('renders API Key authentication controls', async () => {
    const app = createSSRApp(ApiKeySettings)

    const html = await renderToString(app)

    expect(html).toContain('<h2>认证</h2>')
    expect(html).toContain('type="password"')
    expect(html).toContain('>保存</button>')
    expect(html).toContain('清除')
  })

  it('delegates every workspace concept and its empty state', async () => {
    const app = createSSRApp(WorkspaceContents, {
      workspace: {
        ...emptyWorkspaceSnapshot(),
        loadedAt: '2026-08-22T00:00:00.000Z',
      },
    })

    const html = await renderToString(app)

    expect(html).toContain('模型目录（0）')
    expect(html).toContain('没有 Provider')
    expect(html).toContain('会话索引（0）')
    expect(html).toContain('没有会话')
    expect(html).toContain('知识索引（0）')
    expect(html).toContain('没有记忆')
    expect(html).toContain('工具（0）')
    expect(html).toContain('技能（0）')
    expect(html).toContain('数据源（0）')
    expect(html).toContain('执行索引（0）')
    expect(html).toContain('没有 Agent Run')
  })
})
