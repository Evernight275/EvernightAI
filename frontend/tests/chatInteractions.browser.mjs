import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { chromium } from 'playwright'

const base = process.env.FRONTEND_URL || 'http://127.0.0.1:5173'
const screenshots = process.env.SCREENSHOT_DIR || '/tmp/evernight-layout'
await mkdir(screenshots, { recursive: true })
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH })
try {
  for (const width of [1440, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } })
    const errors = []
    page.on('pageerror', (error) => errors.push(error.message))
    let sessions = [
      { session_id: 'one', context_id: 'ctx-one', title: '当前对话', provider_id: 'test', model_id: 'model-a' },
      { session_id: 'two', context_id: 'ctx-two', title: '旧对话', provider_id: 'test', model_id: 'model-a' },
    ]
    let deletionFails = true
    let deletions = 0
    let canceled = 0
    let run
    await page.addInitScript(() => {
      window.EVERNIGHTAI_API_BASE = '/mock-api'
      const originalFetch = window.fetch
      window.fetch = async (url, options) => {
        if (String(url).endsWith('/agent-runs/stream')) {
          window.streamRequest = JSON.parse(options.body)
          return new Response(new ReadableStream({ start(controller) {
            const encoder = new TextEncoder()
            window.pushChatEvent = (event) => controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`))
            window.finishChatStream = () => controller.close()
            options.signal?.addEventListener('abort', () => controller.error(new DOMException('Aborted', 'AbortError')))
          } }), { headers: { 'Content-Type': 'text/event-stream' } })
        }
        return originalFetch(url, options)
      }
    })
    await page.route('**/mock-api/**', async (route) => {
      const path = new URL(route.request().url()).pathname.replace('/mock-api', '')
      const json = (value) => route.fulfill({ json: value })
      if (path === '/health' || path === '/ready') return json({ status: 'ready' })
      if (path === '/providers') return json([
        { provider_id: 'test', name: '主服务', type: 'openai' },
        { provider_id: 'other', name: '备用服务', type: 'openai' },
      ])
      if (path === '/providers/test/models') return json([{ model_id: 'model-a' }])
      if (path === '/providers/other/models') return json([{ model_id: 'model-b' }])
      if (path === '/sessions') return json(sessions)
      if (path.startsWith('/contexts/')) return json({ context_id: path.slice(10), messages: [] })
      if (path.endsWith('/delete')) {
        deletions++
        if (deletionFails) return route.fulfill({ status: 503, json: { error: { message: '删除服务暂时不可用' } } })
        sessions = sessions.filter((session) => !path.includes(`/${session.session_id}/`))
        return route.fulfill({ status: 204 })
      }
      if (path.endsWith('/cancel')) {
        canceled++
        return json({ ...run, status: 'canceled' })
      }
      if (path.startsWith('/agent-runs/')) return json(run)
      return json([])
    })
    async function openSidebar() {
      if (width <= 760 && !await page.locator('.chat-sidebar-dialog').evaluate((el) => el.open)) {
        await page.getByRole('button', { name: '会话管理', exact: true }).click()
      }
    }
    await page.goto(`${base}/chat.html`)
    await openSidebar()
    await page.getByRole('button', { name: '当前对话', exact: true }).click()
    await page.waitForFunction(() => !document.querySelector('#chat-message').disabled)

    await page.getByRole('button', { name: '选择模型', exact: true }).click()
    await page.screenshot({ path: `${screenshots}/${width}-model-picker.png` })
    await page.getByRole('searchbox', { name: '搜索模型' }).fill('备用')
    await page.getByRole('button', { name: 'model-b', exact: true }).click()
    assert.equal(await page.locator('.chat-model-trigger').innerText(), 'model-b')
    await page.locator('#chat-message').fill('stream test')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await page.waitForFunction(() => !!window.pushChatEvent)
    const request = await page.evaluate(() => window.streamRequest)
    assert.equal(request.provider_id, 'other')
    assert.equal(request.model_id, 'model-b')
    run = { run_id: request.metadata.run_id, request, status: 'running' }
    await page.evaluate(() => window.pushChatEvent({ event_type: 'chat_delta', text_delta: '第一段' }))
    await page.getByText('第一段', { exact: true }).waitFor()
    assert.ok(await page.getByRole('button', { name: '停止当前运行' }).isVisible())
    assert.equal(await page.locator('.chat-message--assistant').count(), 1)
    await page.evaluate(() => window.pushChatEvent({ event_type: 'chat_delta', text_delta: '，第二段。' }))
    await page.getByText('第一段，第二段。', { exact: true }).waitFor()
    run = { ...run, status: 'finished', stop_reason: 'finished', response: {
      response_id: 'response-1', model_id: 'model-b', message: { role: 'assistant', content: [{ type: 'text', text: '第一段，第二段。' }] },
    } }
    await page.evaluate((response) => {
      window.pushChatEvent({ event_type: 'chat_completed', response })
      window.finishChatStream()
    }, run.response)
    await page.waitForFunction(() => document.querySelector('.chat-header-status').textContent === '准备就绪')
    assert.equal(await page.locator('.chat-message--assistant').count(), 1)
    assert.equal(await page.locator('.chat-stream-cursor').count(), 0)

    await openSidebar()
    await page.getByRole('button', { name: '删除会话：旧对话', exact: true }).click()
    await page.screenshot({ path: `${screenshots}/${width}-delete-session.png` })
    await page.getByRole('button', { name: '取消', exact: true }).click()
    assert.equal(deletions, 0)
    await page.getByRole('button', { name: '删除会话：旧对话', exact: true }).click()
    await page.getByRole('button', { name: '删除', exact: true }).click()
    await page.locator('.chat-confirm-dialog [role="alert"]').waitFor()
    assert.ok(await page.getByRole('button', { name: '旧对话', exact: true }).count())
    deletionFails = false
    await page.getByRole('button', { name: '删除', exact: true }).click()
    await page.waitForFunction(() => !document.querySelector('.chat-confirm-dialog').open)
    assert.equal(await page.getByRole('button', { name: '旧对话', exact: true }).count(), 0)
    assert.ok(await page.locator('.chat-header-title').innerText().then((text) => text === '当前对话'))
    if (width <= 760) await page.getByRole('button', { name: '关闭会话管理' }).click()

    // Deleting the selected session must cancel its in-flight stream first.
    await page.locator('#chat-message').fill('another stream')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await page.waitForFunction(() => window.streamRequest.messages[0].content[0].text === 'another stream')
    const nextRequest = await page.evaluate(() => window.streamRequest)
    run = { run_id: nextRequest.metadata.run_id, request: nextRequest, status: 'running' }
    await page.evaluate(() => window.pushChatEvent({ event_type: 'chat_delta', text_delta: '正在回答' }))
    await page.getByText('正在回答', { exact: true }).waitFor()
    await page.evaluate(() => window.pushChatEvent({ event_type: 'chat_delta', text_delta: '\n\n' + '长回复段落。\n\n'.repeat(80) }))
    await page.waitForFunction(() => {
      const el = document.querySelector('.chat-view-scroll')
      return el.scrollHeight > el.clientHeight * 2
    })
    await page.evaluate(async () => {
      document.querySelector('.chat-view-scroll').scrollTo({ top: 0, behavior: 'instant' })
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))
      window.pushChatEvent({ event_type: 'chat_delta', text_delta: '阅读时新增的段落。' })
    })
    await page.getByText('阅读时新增的段落。', { exact: true }).waitFor({ state: 'attached' })
    assert.equal(await page.locator('.chat-view-scroll').evaluate((el) => el.scrollTop), 0)
    await page.evaluate(async () => {
      const el = document.querySelector('.chat-view-scroll')
      el.scrollTo({ top: el.scrollHeight, behavior: 'instant' })
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))
      window.pushChatEvent({ event_type: 'chat_delta', text_delta: '\n\n回到底部后继续跟随。' })
    })
    await page.getByText('回到底部后继续跟随。', { exact: true }).waitFor()
    await page.waitForFunction(() => {
      const el = document.querySelector('.chat-view-scroll')
      return el.scrollHeight - el.scrollTop - el.clientHeight < 10
    })
    await openSidebar()
    await page.getByRole('button', { name: '删除会话：当前对话', exact: true }).click()
    await page.getByRole('button', { name: '删除', exact: true }).click()
    await page.waitForFunction(() => !document.querySelector('.chat-confirm-dialog').open)
    assert.equal(canceled, 1)
    assert.equal(await page.locator('.chat-message').count(), 0)
    assert.equal(await page.getByRole('button', { name: '当前对话', exact: true }).count(), 0)
    await page.reload()
    await openSidebar()
    await page.getByText('没有会话', { exact: true }).waitFor()
    assert.equal(await page.locator('.chat-session-button').count(), 0)
    assert.deepEqual(errors, [])
    console.log(`${width}px: model selection, incremental stream, deduplication, deletion failure/cancel/success and persistence passed`)
    await page.close()
  }
} finally {
  await browser.close()
}
