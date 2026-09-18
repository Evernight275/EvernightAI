import assert from 'node:assert/strict'
import { chromium } from 'playwright'
import { mkdir } from 'node:fs/promises'
const screenshots = process.env.SCREENSHOT_DIR || '/tmp/evernight-layout'
await mkdir(screenshots, { recursive: true })
const base = process.env.FRONTEND_URL || 'http://127.0.0.1:5173'
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH })
try {
  for (const width of [1440, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } })
    const errors = []
    const calls = []
    let socketClosed = false
    let providers = []
    let memories = []
    let failCreate = true
    let session = { session_id: 'session-1', context_id: 'ctx-1', title: '原始标题', provider_id: 'test', model_id: 'model-a', metadata: { preserve: true } }
    const run = { run_id: 'run-1', request: { provider_id: 'test', model_id: 'model-a', context_id: 'ctx-1' }, status: 'paused', pending_approval_requests: [{ approval_id: 'approval-1', tool_call_id: 'call-1', tool_name: 'write_file', permissions: ['write'], tool_call: { path: 'example.txt' } }] }
    page.on('pageerror', error => errors.push(error.message))
    await page.addInitScript(() => { window.EVERNIGHTAI_API_BASE = '/mock-api' })
    await page.routeWebSocket('**/ws', socket => {
      socket.onMessage(raw => {
        const message = JSON.parse(String(raw))
        if (message.client_event?.event_name === 'agent_run.subscribe') socket.send(JSON.stringify({ message_type: 'agent_trace', run_id: 'run-1', trace_event: { event_type: 'run_started', summary: '实时事件已到达' }, payload: { sequence: 1 } }))
      })
      socket.onClose(() => { socketClosed = true })
    })
    await page.route('**/mock-api/**', async route => {
      const url = new URL(route.request().url())
      const path = url.pathname.replace('/mock-api', '')
      const method = route.request().method()
      const data = method === 'GET' ? null : route.request().postDataJSON()
      calls.push({ path, method, data })
      const json = value => route.fulfill({ json: value })
      if (path === '/health' || path === '/ready') return json({ status: 'ready' })
      if (path === '/providers' && method === 'POST') {
        if (failCreate) { failCreate = false; return route.fulfill({ status: 503, json: { error: { message: '服务暂时不可用' } } }) }
        const { api_key, ...info } = data; providers.push(info); return json(info)
      }
      if (path === '/providers') return json(providers)
      if (path.endsWith('/models')) return json([{ model_id: 'model-a' }])
      if (path === '/providers/test/delete') { providers = []; return route.fulfill({ status: 204 }) }
      if (path === '/memories' && method === 'POST') { memories.push(data); return json(data) }
      if (path === '/memories') return json(memories)
      if (path === '/memories/select') return json({ memories })
      if (path.startsWith('/memories/')) {
        const id = path.split('/')[2]; const item = memories.find(item => item.memory_id === id)
        if (path.endsWith('/delete')) { memories = []; return route.fulfill({ status: 204 }) }
        if (path.endsWith('/disable')) item.is_enabled = false
        if (path.endsWith('/enable')) item.is_enabled = true
        if (method === 'PUT') Object.assign(item, data)
        return json(item)
      }
      if (path === '/sessions') return json([session])
      if (path === '/sessions/session-1') { if (method === 'PUT') session = data; return json(session) }
      if (path === '/contexts/ctx-1/compose-preview') return json({ ...data, metadata: { ...data.metadata, preview: true } })
      if (path === '/contexts/ctx-1') return json({ context_id: 'ctx-1', messages: [] })
      if (path === '/skills') return json([{ name: 'echo', description: '回显技能', input_schema: { type: 'object', properties: { text: { type: 'string' } } } }])
      if (path === '/data-analysis/sources') return json([{ source_id: 'runtime', name: '运行统计' }])
      if (path === '/data-analysis/sources/runtime') return json({ source_id: 'runtime', name: '运行统计' })
      if (path.endsWith('/fields')) return json([{ field_id: 'status', name: '状态', field_type: 'string' }])
      if (path.endsWith('/metrics')) return json([{ metric_id: 'count', name: '运行次数', aggregation: 'count' }])
      if (path === '/data-analysis/statistics') return json({ source_id: 'runtime', rows: [{ dimensions: {}, metrics: { count: 3 } }] })
      if (path === '/data-analysis/analyze') return json({ source_id: 'runtime', narrative: '共有三次运行', insights: [] })
      if (path === '/agent-runs') return json([run])
      if (path === '/agent-runs/run-1') return json(run)
      if (path.endsWith('/resume')) return json({ ...run, status: 'finished', pending_approval_requests: [] })
      if (path === '/agent-runs/stream') return route.fulfill({ contentType: 'text/event-stream', body: 'data: [DONE]\n\n' })
      if (path.startsWith('/agent-runs/')) return json({ ...run, run_id: path.split('/')[2], status: 'finished', stop_reason: 'finished', pending_approval_requests: [], response: { model_id: 'model-a', message: { role: 'assistant', content: [{ type: 'text', text: '你好！' }] } } })
      return json([])
    })
    await page.goto(base)
    await page.getByRole('button', { name: '连接与认证', exact: true }).click()
    await page.getByText('添加模型服务', { exact: true }).click()
    await page.getByLabel('服务名称', { exact: true }).fill('测试服务')
    await page.getByLabel('服务标识', { exact: true }).fill('test')
    await page.getByLabel('服务密钥', { exact: true }).fill('test-only-secret')
    await page.getByLabel('模型 ID', { exact: true }).fill('model-a')
    await page.getByRole('button', { name: '添加服务', exact: true }).click()
    await page.getByRole('alert').filter({ hasText: '服务暂时不可用' }).waitFor()
    assert.equal(await page.getByLabel('服务密钥', { exact: true }).inputValue(), 'test-only-secret')
    await page.getByRole('button', { name: '添加服务', exact: true }).click()
    await page.getByText('模型服务已添加', { exact: true }).waitFor()
    await page.screenshot({ path: `${screenshots}/${width}-provider-management.png` })
    assert.equal(await page.getByLabel('服务密钥', { exact: true }).inputValue(), '')
    await page.getByRole('button', { name: '记忆管理', exact: true }).click()
    await page.getByLabel('记忆内容', { exact: true }).fill('喜欢简洁回复')
    await page.getByRole('button', { name: '保存记忆', exact: true }).click()
    await page.getByText('记忆已保存', { exact: true }).waitFor()
    await page.getByRole('button', { name: '编辑', exact: true }).click()
    await page.getByLabel('记忆内容', { exact: true }).fill('偏好中文回复')
    await page.getByRole('button', { name: '保存记忆', exact: true }).click()
    await page.getByText('偏好中文回复', { exact: true }).waitFor()
    await page.screenshot({ path: `${screenshots}/${width}-memory-management.png` })
    await page.getByRole('button', { name: '停用', exact: true }).click()
    await page.getByRole('button', { name: '启用', exact: true }).waitFor()
    await page.getByRole('button', { name: '删除', exact: true }).click()
    assert.equal(memories.length, 1)
    await page.getByRole('button', { name: '确认删除记忆', exact: true }).click()
    await page.getByText('没有匹配的记忆。', { exact: true }).waitFor()
    await page.getByRole('button', { name: '运行管理', exact: true }).click()
    await page.getByRole('button', { name: '管理运行', exact: true }).click()
    await page.getByRole('button', { name: '实时轨迹', exact: true }).click()
    await page.getByText('run_started · 实时事件已到达', { exact: true }).waitFor()
    await page.getByRole('button', { name: '停止订阅', exact: true }).click()
    assert.ok(await page.getByRole('button', { name: '继续运行', exact: true }).isDisabled())
    await page.getByLabel('审批决定').selectOption('denied')
    await page.getByRole('button', { name: '继续运行', exact: true }).click()
    await page.getByRole('button', { name: '确认操作', exact: true }).click()
    await page.waitForFunction(() => !document.querySelector('[aria-label="运行管理"]').textContent.includes('确认继续'))
    assert.deepEqual(calls.find(call => call.path.endsWith('/resume')).data.approvals, [{ approval_id: 'approval-1', tool_call_id: 'call-1', status: 'denied' }])
    await page.getByRole('button', { name: '工作区资源', exact: true }).click()
    await page.getByLabel('操作', { exact: true }).selectOption('statistics')
    await page.getByLabel('高级参数（JSON）').fill('{')
    await page.getByRole('button', { name: '查询统计', exact: true }).click()
    await page.getByRole('alert').waitFor()
    assert.equal(calls.filter(call => call.path === '/data-analysis/statistics').length, 0)
    await page.getByLabel('高级参数（JSON）').fill('{"source_id":"runtime","metrics":["count"]}')
    await page.getByRole('button', { name: '查询统计', exact: true }).click()
    await page.getByRole('region', { name: '操作结果' }).waitFor()
    assert.ok(await page.locator('.settings-shell').evaluate(el => el.scrollWidth <= el.clientWidth))
    assert.ok(socketClosed)
    await page.getByRole('button', { name: '数据分析', exact: true }).click()
    await page.getByLabel('数据源', { exact: false }).selectOption('runtime')
    await page.getByLabel('运行次数', { exact: false }).check()
    await page.getByRole('button', { name: '查询统计', exact: true }).click()
    await page.getByRole('cell', { name: '3', exact: true }).waitFor()
    await page.getByLabel('分析问题', { exact: true }).fill('运行情况如何？')
    await page.getByRole('button', { name: '分析数据', exact: true }).click()
    await page.getByText('共有三次运行', { exact: true }).waitFor()
    await page.screenshot({ path: `${screenshots}/${width}-data-analysis.png` })
    await page.goto(`${base}/chat.html`)
    if (width <= 760) await page.getByRole('button', { name: '会话管理', exact: true }).click()
    await page.getByRole('button', { name: '原始标题', exact: true }).click()
    await page.getByRole('button', { name: '编辑会话标题', exact: true }).click()
    await page.getByLabel('会话标题', { exact: true }).fill('新的标题')
    await page.getByRole('button', { name: '保存标题', exact: true }).click()
    await page.getByRole('heading', { name: '新的标题', exact: true }).waitFor()
    assert.deepEqual(session.metadata, { preserve: true })
    await page.getByText('技能与上下文', { exact: true }).click()
    await page.getByLabel('本轮技能').selectOption('echo')
    await page.getByLabel('技能参数（JSON）').fill('{"text":"hello"}')
    await page.locator('#chat-message').fill('你好')
    await page.getByRole('button', { name: '预览上下文', exact: true }).click()
    await page.getByLabel('上下文预览', { exact: true }).waitFor()
    const preview = calls.find(call => call.path.endsWith('/compose-preview')).data
    assert.deepEqual(preview.skills, [{ skill_name: 'echo', variables: { text: 'hello' } }])
    assert.equal(preview.metadata.session_id, 'session-1')
    await page.getByText('技能与上下文', { exact: true }).click()
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await page.waitForFunction(() => document.querySelector('.chat-header-status').textContent === '准备就绪')
    assert.deepEqual(calls.find(call => call.path === '/agent-runs/stream').data.skills, preview.skills)
    assert.deepEqual(errors, [])
    await page.close()
    console.log(`${width}px: provider error/retry, memory CRUD, approvals, resource validation, rename and skill preview/send passed`)
  }
} finally { await browser.close() }
