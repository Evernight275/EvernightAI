import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { chromium } from 'playwright'

const base = process.env.FRONTEND_URL || 'http://127.0.0.1:5173'
const screenshots = process.env.SCREENSHOT_DIR || '/tmp/evernight-layout'
await mkdir(screenshots, { recursive: true })
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
})
try {
  for (const width of [1440, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } })
    const errors = []
    page.on('pageerror', (error) => errors.push(error.message))
    let run
    let failRead = true
    const readIds = []
    await page.addInitScript(() => {
      window.EVERNIGHTAI_API_BASE = '/mock-api'
      window.toolStreamStarts = 0
      window.toolResumes = []
      const original = window.fetch
      window.fetch = async (url, options) => {
        if (String(url).endsWith('/agent-runs/stream') || String(url).endsWith('/resume/stream')) {
          const resume = String(url).endsWith('/resume/stream')
          if (resume) window.toolResumes.push(JSON.parse(options.body))
          else {
            window.toolStreamStarts++
            window.toolRequest = JSON.parse(options.body)
          }
          return new Response(
            new ReadableStream({
              start(controller) {
                const encoder = new TextEncoder()
                window.toolEvent = (event) =>
                  controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`))
                window.toolDisconnect = () => controller.error(new TypeError('connection lost'))
                window.toolFinish = () => controller.close()
                options.signal?.addEventListener('abort', () =>
                  controller.error(new DOMException('Aborted', 'AbortError')),
                )
              },
            }),
            { headers: { 'content-type': 'text/event-stream' } },
          )
        }
        return original(url, options)
      }
    })
    await page.route('**/mock-api/**', async (route) => {
      const path = new URL(route.request().url()).pathname.replace('/mock-api', '')
      const json = (value) => route.fulfill({ json: value })
      if (path === '/health' || path === '/ready') return json({ status: 'ready' })
      if (path === '/providers') return json([{ provider_id: 'p', name: 'Test', type: 'openai' }])
      if (path === '/providers/p/models') return json([{ model_id: 'model' }])
      if (path === '/sessions')
        return json([
          {
            session_id: 's',
            context_id: 'ctx',
            title: '工具进度测试',
            provider_id: 'p',
            model_id: 'model',
          },
        ])
      if (path.startsWith('/contexts/')) return json({ context_id: 'ctx', messages: [] })
      if (path.startsWith('/agent-runs/')) {
        readIds.push(path)
        if (failRead) {
          failRead = false
          return route.abort('connectionfailed')
        }
        return json(run)
      }
      return json([])
    })
    await page.goto(`${base}/chat.html`)
    if (width <= 760) await page.getByRole('button', { name: '会话管理', exact: true }).click()
    await page.getByRole('button', { name: '工具进度测试', exact: true }).click()
    await page.locator('#chat-message').fill('检查配置并修改文件')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await page.waitForFunction(() => !!window.toolRequest)
    const request = await page.evaluate(() => window.toolRequest)
    const call = (id, name, path) => ({
      tool_call_id: id,
      tool_call: { name, arguments: { path } },
    })
    const read = call('read', 'read_text_file', 'config.toml')
    const write = call('write', 'write_text_file', 'config.toml')
    const remove = call('remove', 'delete_file', 'old.toml')
    const response = (text, calls = []) => ({
      model_id: 'model',
      message: { role: 'assistant', content: [{ type: 'text', text }], tool_calls: calls },
    })
    let trace = [
      { sequence: 1, event_type: 'chat_completed', response: response('先检查配置。', [read]) },
      { sequence: 2, event_type: 'tool_started', tool_call: read },
    ]
    run = { run_id: request.metadata.run_id, request, status: 'running', trace }
    await page.evaluate((events) => events.forEach(window.toolEvent), trace)
    await page.locator('.chat-inline-tool-status').filter({ hasText: '执行中' }).waitFor()
    await page.evaluate(() => window.toolDisconnect())
    await page.getByText('连接中断，正在自动重连…', { exact: true }).waitFor()
    await page.getByText('连接已恢复，正在同步运行进度…', { exact: true }).waitFor()
    const approvals = [write, remove].map((tool) => ({
      approval_id: `${tool.tool_call_id}-approval`,
      tool_call_id: tool.tool_call_id,
      tool_name: tool.tool_call.name,
      tool_call: tool.tool_call,
      safety_level: 'sensitive',
      permissions: ['filesystem', 'write'],
      reason: '需要修改工作文件',
    }))
    trace = [
      ...trace,
      {
        sequence: 3,
        event_type: 'tool_completed',
        tool_call: read,
        tool_result: { tool_call_id: 'read', tool_call_result: { content: '配置文件共 24 行。' } },
      },
      {
        sequence: 4,
        event_type: 'chat_completed',
        response: response('需要你确认文件修改。', [write, remove]),
      },
      ...approvals.map((approval, i) => ({
        sequence: 5 + i,
        event_type: 'tool_approval_requested',
        approval_request: approval,
      })),
      { sequence: 7, event_type: 'run_paused' },
    ]
    run = { ...run, status: 'paused', trace, pending_approval_requests: approvals }
    const cards = page.locator('.chat-tool-card')
    const writeCard = cards.filter({ hasText: 'write_text_file' })
    await writeCard.getByRole('button', { name: '批准', exact: true }).waitFor()
    assert.equal(await cards.count(), 3)
    assert.equal(await page.getByText('先检查配置。', { exact: true }).count(), 1)
    assert.ok(await cards.first().getByText('配置文件共 24 行。', { exact: true }).isVisible())
    await writeCard.getByRole('button', { name: '批准', exact: true }).click()
    const footer = page.locator('.chat-view-footer')
    assert.ok(
      await footer
        .locator('.chat-tool-approval')
        .filter({ hasText: 'write_text_file' })
        .getByRole('button', { name: '批准', exact: true })
        .isDisabled(),
    )
    assert.equal(await writeCard.locator('.chat-inline-tool-status').innerText(), '准备')
    await footer
      .locator('.chat-tool-approval')
      .filter({ hasText: 'delete_file' })
      .getByRole('button', { name: '拒绝', exact: true })
      .click()
    await page.waitForFunction(() => window.toolResumes.length === 1)
    const resumes = await page.evaluate(() => window.toolResumes)
    assert.deepEqual(
      resumes[0].approvals.map((item) => item.status),
      ['approved', 'denied'],
    )
    const finalResponse = response('配置修改失败，已保留原文件。')
    const resumed = [
      { sequence: 8, event_type: 'tool_started', tool_call: write },
      {
        sequence: 9,
        event_type: 'tool_failed',
        tool_call: write,
        error_type: 'PermissionError',
        error_message: 'config.toml:12: permission denied',
      },
      {
        sequence: 10,
        event_type: 'tool_approval_decided',
        tool_call: remove,
        metadata: { allowed: false },
      },
      { sequence: 11, event_type: 'chat_completed', response: finalResponse },
      { sequence: 12, event_type: 'run_stopped' },
    ]
    run = {
      ...run,
      status: 'finished',
      stop_reason: 'finished',
      response: finalResponse,
      trace: [...trace, ...resumed],
      pending_approval_requests: [],
    }
    await page.evaluate((events) => {
      events.forEach(window.toolEvent)
      window.toolFinish()
    }, resumed)
    await page.getByRole('button', { name: '发送', exact: true }).waitFor()
    assert.equal(await writeCard.locator('.chat-inline-tool-status').innerText(), '失败')
    await writeCard.getByRole('button', { name: '定位错误', exact: true }).click()
    assert.ok(
      await writeCard
        .getByLabel('write_text_file 调用结果', { exact: true })
        .evaluate((element) => document.activeElement === element),
    )
    assert.ok(await writeCard.getByText('PermissionError', { exact: false }).isVisible())
    assert.equal(await page.evaluate(() => window.toolStreamStarts), 1)
    assert.equal(await page.locator('.chat-tool-card').count(), 3)
    assert.ok(readIds.every((path) => path === `/agent-runs/${run.run_id}`))
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    await page.screenshot({ path: `${screenshots}/${width}-tool-progress.png` })
    assert.deepEqual(errors, [])
    await page.close()
  }
  console.log('Tool progress browser checks passed at desktop and mobile widths.')
} finally {
  await browser.close()
}
