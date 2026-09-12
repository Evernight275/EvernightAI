import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { chromium } from 'playwright'

const base = process.env.FRONTEND_URL || 'http://127.0.0.1:5173'
const screenshots = process.env.SCREENSHOT_DIR || '/tmp/evernight-layout'
await mkdir(screenshots, { recursive: true })

const session = {
  session_id: 'layout-test', context_id: 'layout-context', title: '热传导计算',
  provider_id: 'test', model_id: 'test-model', created_at: '2026-09-05T00:00:00Z',
}
const approvals = Array.from({ length: 3 }, (_, index) => ({
  approval_id: `approval-${index}`, tool_call_id: `call-${index}`,
  tool_name: 'write_text_file', safety_level: 'sensitive', permissions: ['write', 'filesystem'],
  tool_call: { name: 'write_text_file', arguments: {
    project: 'thermal', path: `src/heat_${index}.py`, content: 'print("heat")\n'.repeat(500),
  } },
}))

const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
})
try {
  for (const [width, height] of [[1440, 900], [1024, 600], [390, 844], [320, 640], [844, 390]]) {
    const page = await browser.newPage({ viewport: { width, height } })
    const errors = []
    const decisions = []
    let run
    let failNext = false
    let cancellations = 0
    const createdSessions = []
    page.on('pageerror', (error) => errors.push(error.message))
    await page.addInitScript(() => { window.EVERNIGHTAI_API_BASE = '/mock-api' })
    await page.route('**/mock-api/**', async (route) => {
      const path = new URL(route.request().url()).pathname.replace('/mock-api', '')
      const json = (value) => route.fulfill({ json: value })
      const sse = () => route.fulfill({ contentType: 'text/event-stream', body: 'data: [DONE]\n\n' })
      if (path === '/health' || path === '/ready') return json({ status: 'ready' })
      if (path === '/providers') return json([{ provider_id: 'test', name: 'Test', type: 'openai' }])
      if (path === '/providers/test/models') return json([{ model_id: 'test-model' }])
      if (path === '/tools') return json([{ name: 'write_text_file', description: 'Write a file' }])
      if (path === '/sessions' && route.request().method() === 'POST') {
        const created = route.request().postDataJSON()
        createdSessions.push(created)
        return json(created)
      }
      if (path === '/sessions') return json([session])
      if (path === '/contexts/layout-context') return json({ context_id: session.context_id, messages: [
        { role: 'user', content: [{ type: 'text', text: '计算一维热传导。' }] },
        { role: 'assistant', content: [{ type: 'text', text: [
          '## 离散方程', '', String.raw`\[ -\frac{d}{dx}\left(kA\frac{dT}{dx}\right) = q A \]`,
          '', '```python', 'import numpy as np', 'x = np.linspace(0, 1, 10)', '# ' + 'long line '.repeat(30), '```',
        ].join('\n') }] },
      ] })
      if (path === '/agent-runs/stream') {
        const request = route.request().postDataJSON()
        run = { run_id: request.metadata.run_id, request, status: 'paused', steps: [],
          pending_approval_requests: approvals }
        if (failNext) {
          failNext = false
          run = { ...run, status: 'failed', stop_reason: 'tool_error', pending_approval_requests: [] }
          return route.fulfill({ status: 503, json: { error: { message: 'Provider unavailable' } } })
        }
        return sse()
      }
      if (path.endsWith('/cancel')) {
        cancellations++
        run = { ...run, status: 'canceled' }
        return json(run)
      }
      if (path.endsWith('/resume/stream')) {
        decisions.push(route.request().postDataJSON().approvals)
        run = { ...run, status: 'finished', stop_reason: 'finished', pending_approval_requests: [],
          response: { model_id: 'test-model', message: { role: 'assistant', content: [{ type: 'text', text: '处理完成。' }] } } }
        return sse()
      }
      if (path.endsWith('/retry/stream')) {
        run = { ...run, run_id: route.request().postDataJSON().retried_run_id,
          status: 'paused', stop_reason: null, pending_approval_requests: approvals }
        return sse()
      }
      if (path.startsWith('/agent-runs/')) return json(run)
      return json([])
    })

    await page.goto(`${base}/chat.html`)
    await page.locator('.chat-welcome').waitFor()
    await page.screenshot({ path: `${screenshots}/${width}x${height}-welcome.png` })
    if (width > 760) {
      await page.getByRole('button', { name: '收起侧栏', exact: true }).click()
      await page.waitForFunction(() => !document.querySelector('.chat-sidebar-dialog').open)
      assert.equal((await page.locator('.chat-main').boundingBox()).width, width)
    }
    await page.getByRole('button', { name: '会话管理', exact: true }).click()
    await page.getByRole('searchbox', { name: '搜索会话' }).fill('不存在的标题')
    await page.getByText('没有找到匹配的会话').waitFor()
    assert.equal(await page.getByRole('button', { name: '热传导计算', exact: true }).count(), 0)
    await page.getByRole('searchbox', { name: '搜索会话' }).fill('热传导')
    await page.getByRole('button', { name: '热传导计算', exact: true }).click()
    await page.locator('#chat-message').waitFor({ state: 'visible' })
    await page.waitForFunction(() => !document.querySelector('#chat-message').disabled)
    const editor = page.locator('#chat-message')
    const shortHeight = (await editor.boundingBox()).height
    await editor.fill('第一行\n第二行\n第三行\n第四行')
    await page.waitForFunction((minimum) => document.querySelector('#chat-message').getBoundingClientRect().height > minimum, shortHeight)
    await editor.fill('')
    await page.waitForFunction((expected) => document.querySelector('#chat-message').getBoundingClientRect().height === expected, shortHeight)
    await page.screenshot({ path: `${screenshots}/${width}x${height}-conversation.png` })
    const headerHeight = (await page.locator('.chat-view-header').boundingBox()).height
    assert.equal(await page.locator('.chat-request-status').count(), 0)

    async function send() {
      await page.locator('#chat-message').fill('请写入这三个文件。')
      await page.getByRole('button', { name: '发送', exact: true }).click()
      await page.locator('.chat-approval-group').waitFor({ state: 'visible' })
    }
    async function checkBounds() {
      const bounds = await page.evaluate(() => {
        const rect = (selector) => {
          const { top, bottom, height } = document.querySelector(selector).getBoundingClientRect()
          return { top, bottom, height }
        }
        return { header: rect('.chat-view-header'), body: rect('.chat-view-scroll'),
          footer: rect('.chat-view-footer'), editor: rect('#chat-message'),
          documentWidth: document.documentElement.scrollWidth,
          documentHeight: document.documentElement.scrollHeight }
      })
      assert.equal(bounds.header.height, headerHeight)
      assert.ok(bounds.body.height > 40, JSON.stringify(bounds))
      assert.ok(bounds.body.bottom <= bounds.footer.top + 1)
      assert.ok(bounds.editor.bottom <= height)
      assert.ok(bounds.footer.bottom <= height + 1, JSON.stringify(bounds))
      assert.ok(bounds.documentWidth <= width)
      assert.ok(bounds.documentHeight <= height + 1, JSON.stringify(bounds))
    }
    await send()
    await checkBounds()
    assert.equal(await page.locator('.chat-details-panel').evaluate((el) => el.open), false)
    assert.equal(await page.locator('.chat-view-scroll .chat-tool-approval').count(), 0)
    await page.locator('.chat-approval-payload summary').first().click()
    await checkBounds()
    await page.locator('.chat-approval-payload summary').first().click()
    await page.screenshot({ path: `${screenshots}/${width}x${height}-approvals.png` })

    await page.getByRole('button', { name: '运行详情', exact: true }).click()
    assert.ok(await page.locator('.chat-details-panel').evaluate((el) => el.matches(':modal')))
    await page.getByRole('button', { name: '关闭运行详情' }).focus()
    await page.keyboard.press('Shift+Tab')
    assert.ok(await page.locator('.chat-details-panel').evaluate((el) => el.contains(document.activeElement)))
    await page.locator('.chat-details-panel .chat-raw-details summary').first().click()
    await page.screenshot({ path: `${screenshots}/${width}x${height}-details.png` })
    await page.keyboard.press('Escape')
    await page.waitForFunction(() => !document.querySelector('.chat-details-panel').open)
    assert.equal(await page.evaluate(() => document.activeElement.getAttribute('aria-label')), '运行详情')
    await page.getByRole('button', { name: '运行详情', exact: true }).click()
    await page.getByRole('button', { name: '关闭运行详情' }).click()
    await page.waitForFunction(() => !document.querySelector('.chat-details-panel').open)
    if (width > 480) {
      await page.getByRole('button', { name: '运行详情', exact: true }).click()
      await page.mouse.click(1, 1)
      await page.waitForFunction(() => !document.querySelector('.chat-details-panel').open)
    }
    await page.getByRole('button', { name: '停止当前运行' }).click()
    await page.waitForFunction(() => document.querySelector('.chat-header-status').textContent === '已取消')
    assert.equal(cancellations, 1)

    await send()
    await page.getByRole('button', { name: '批准', exact: true }).nth(0).click()
    assert.ok(await page.getByRole('button', { name: '批准', exact: true }).nth(0).isDisabled())
    await page.getByRole('button', { name: '拒绝', exact: true }).nth(1).click()
    await page.getByRole('button', { name: '批准', exact: true }).nth(2).click()
    await page.waitForFunction(() => document.querySelector('.chat-header-status').textContent === '准备就绪')
    assert.deepEqual(decisions[0].map((decision) => decision.status), ['approved', 'denied', 'approved'])
    assert.equal(await page.locator('.chat-request-status').count(), 0)

    failNext = true
    await page.locator('#chat-message').fill('测试请求失败。')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await page.locator('.chat-status-error[role="alert"]').waitFor()
    await page.getByRole('button', { name: '重试', exact: true }).click()
    await page.locator('.chat-approval-group').waitFor()
    await checkBounds()
    if (width <= 760) {
      await page.getByRole('button', { name: '会话管理', exact: true }).click()
      await page.screenshot({ path: `${screenshots}/${width}x${height}-navigation.png` })
      await page.keyboard.press('Escape')
      await page.waitForFunction(() => !document.querySelector('.chat-sidebar-dialog').open)
      await page.setViewportSize({ width: 1024, height: 768 })
      await page.waitForFunction(() => document.querySelector('.chat-sidebar-dialog').open)
      assert.equal(await page.locator('.chat-sidebar-dialog').evaluate((el) => el.matches(':modal')), false)
      await page.setViewportSize({ width, height })
      await page.waitForFunction(() => !document.querySelector('.chat-sidebar-dialog').open)
    }
    await page.reload()
    await page.waitForFunction(() => !document.querySelector('#chat-message').disabled)
    await page.locator('#chat-message').fill('直接开始一段新对话。')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await page.locator('.chat-approval-group').waitFor()
    assert.equal(createdSessions.length, 1)
    assert.equal(createdSessions[0].provider_id, 'test')
    assert.equal(createdSessions[0].model_id, 'test-model')
    assert.ok(await page.locator('.chat-message--user').innerText().then((text) => text.includes('直接开始一段新对话。')))
    await checkBounds()
    assert.deepEqual(errors, [])
    await page.route('**/mock-api/sessions', (route) => route.fulfill({ json:
      Array.from({ length: 40 }, (_, index) => ({ ...session,
        session_id: `sidebar-${index}`, title: `会话 ${index + 1}`,
      })),
    }))
    await page.reload()
    if (width <= 760) await page.getByRole('button', { name: '会话管理', exact: true }).click()
    await page.getByRole('button', { name: '会话 40', exact: true }).waitFor()
    const footerBefore = await page.locator('.chat-sidebar-settings').boundingBox()
    await page.getByRole('button', { name: '会话 40', exact: true }).scrollIntoViewIfNeeded()
    const footerAfter = await page.locator('.chat-sidebar-settings').boundingBox()
    assert.equal(footerAfter.y, footerBefore.y)
    assert.equal(footerAfter.height, footerBefore.height)
    assert.ok(footerBefore.y + footerBefore.height <= height + 1)
    assert.ok(await page.locator('.chat-sidebar-sessions').evaluate((el) => el.scrollTop > 0))
    await page.screenshot({ path: `${screenshots}/${width}x${height}-sidebar-long.png` })
    console.log(`${width}x${height}: layout, dialog focus/Escape, stop, approvals and retry passed`)
    await page.close()
  }
} finally {
  await browser.close()
}
