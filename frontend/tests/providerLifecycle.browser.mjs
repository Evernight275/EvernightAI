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
    await page.emulateMedia({ reducedMotion: 'reduce' })
    const errors = []
    const calls = []
    const providers = [
      { provider_id: 'off', name: '已停用的服务', type: 'openai', is_enabled: false, model: { off: { model_id: 'off-model' } } },
      { provider_id: 'main', name: '主服务', type: 'openai', is_enabled: true, model: { main: { model_id: 'main-model' } } },
      { provider_id: 'spare', name: '备用服务', type: 'openai', is_enabled: true, model: { spare: { model_id: 'spare-model' } } },
    ]
    const session = { session_id: 'session-1', context_id: 'ctx-1', title: '现有会话', provider_id: 'main', model_id: 'main-model' }
    let failDisable = true
    let failEnable = true
    page.on('pageerror', error => errors.push(error.message))
    await page.addInitScript(() => { window.EVERNIGHTAI_API_BASE = '/mock-api' })
    await page.route('**/mock-api/**', async route => {
      const path = new URL(route.request().url()).pathname.replace('/mock-api', '')
      const method = route.request().method()
      const data = method === 'GET' ? null : route.request().postDataJSON()
      calls.push({ path, method, data })
      const json = value => route.fulfill({ json: value })
      if (path === '/health' || path === '/ready') return json({ status: 'ready' })
      if (path === '/providers') return json(providers)
      if (path.startsWith('/providers/')) {
        const provider = providers.find(item => item.provider_id === path.split('/')[2])
        if (path.endsWith('/models')) {
          assert.notEqual(provider.is_enabled, false, 'disabled providers must not trigger model discovery')
          return json(Object.values(provider.model))
        }
        if (path.endsWith('/config')) return json({ ...provider, has_api_key: true, api_key_secret_ref: 'env:KEY' })
        if (method === 'PATCH') {
          if (data.is_enabled === false && failDisable) {
            failDisable = false
            return route.fulfill({ status: 503, json: { error: { message: '停用暂时失败' } } })
          }
          if (data.is_enabled === true && failEnable) {
            failEnable = false
            return route.fulfill({ status: 400, json: { error: { message: '启用失败：密钥未配置' } } })
          }
          Object.assign(provider, data)
          return json(provider)
        }
      }
      if (path === '/sessions') return json([session])
      if (path === '/sessions/session-1') return json(session)
      if (path === '/contexts/ctx-1') return json({ context_id: 'ctx-1', messages: [
        { role: 'assistant', content: [{ type: 'text', text: '已经保存的回复' }] },
      ] })
      return json([])
    })
    async function openSidebar() {
      if (width <= 760 && !(await page.locator('.chat-sidebar-dialog').evaluate(el => el.open))) {
        await page.getByRole('button', { name: '会话管理', exact: true }).click()
      }
    }
    async function openSettings() {
      await openSidebar()
      await page.getByRole('button', { name: '设置', exact: true }).click()
      await page.getByRole('button', { name: '连接与认证', exact: true }).click()
    }
    async function closeSettings() {
      await page.getByRole('button', { name: '关闭设置', exact: true }).click()
      await page.waitForFunction(() => !document.querySelector('.settings-dialog').open)
      await page.locator('.settings-dialog').waitFor({ state: 'hidden' })
    }
    await page.goto(`${base}/chat.html`)
    await openSidebar()
    await page.getByRole('button', { name: '现有会话', exact: true }).click()
    await page.getByText('已经保存的回复', { exact: true }).waitFor()
    await page.locator('#chat-message').fill('保留草稿')
    assert.ok(await page.getByRole('button', { name: '发送', exact: true }).isEnabled())

    await openSettings()
    await page.getByRole('button', { name: '停用服务 主服务', exact: true }).click()
    await page.getByRole('alert').filter({ hasText: '停用暂时失败' }).waitFor()
    assert.equal(providers[1].is_enabled, true)
    await page.getByRole('button', { name: '停用服务 主服务', exact: true }).click()
    await page.getByRole('button', { name: '启用服务 主服务', exact: true }).waitFor()
    assert.deepEqual(calls.filter(call => call.method === 'PATCH').at(-1).data, { is_enabled: false })
    assert.ok(await page.locator('.settings-shell').evaluate(el => el.scrollWidth <= el.clientWidth))
    await page.screenshot({ path: `${screenshots}/${width}-provider-disabled.png` })
    await page.getByRole('button', { name: '编辑服务 主服务', exact: true }).click()
    await page.getByLabel('服务名称', { exact: true }).fill('主服务已编辑')
    await page.getByRole('button', { name: '保存服务', exact: true }).click()
    await page.getByRole('button', { name: '启用服务 主服务已编辑', exact: true }).waitFor()
    assert.equal(providers[1].is_enabled, false)
    await closeSettings()
    await page.getByText('当前模型服务已停用，请启用该服务或选择其他模型。', { exact: true }).waitFor()
    assert.equal(await page.locator('#chat-message').inputValue(), '保留草稿')
    assert.equal(await page.locator('.chat-model-trigger').innerText(), 'main-model')
    assert.ok(await page.getByRole('button', { name: '发送', exact: true }).isDisabled())
    await page.getByText('技能与上下文', { exact: true }).click()
    await page.locator('.chat-composer').getByLabel('模型 ID', { exact: true }).fill('undeclared-model')
    assert.ok(await page.getByRole('button', { name: '发送', exact: true }).isDisabled())
    await page.getByRole('button', { name: '选择模型', exact: true }).click()
    assert.equal(await page.getByRole('button', { name: 'off-model', exact: true }).count(), 0)
    assert.equal(await page.getByRole('button', { name: 'main-model', exact: true }).count(), 0)
    await page.getByRole('button', { name: 'spare-model', exact: true }).click()
    await page.locator('.chat-composer').getByLabel('模型 ID', { exact: true }).fill('spare-custom')
    assert.ok(await page.getByRole('button', { name: '发送', exact: true }).isEnabled())
    assert.equal(await page.getByText('当前模型服务已停用，请启用该服务或选择其他模型。', { exact: true }).count(), 0)

    await openSettings()
    await page.getByRole('button', { name: '启用服务 主服务已编辑', exact: true }).click()
    await page.getByRole('alert').filter({ hasText: '启用失败：密钥未配置' }).waitFor()
    assert.equal(providers[1].is_enabled, false)
    await page.getByRole('button', { name: '启用服务 主服务已编辑', exact: true }).click()
    await page.getByRole('button', { name: '停用服务 主服务已编辑', exact: true }).waitFor()
    await closeSettings()
    assert.equal(await page.locator('.chat-model-trigger').innerText(), 'spare-custom')
    await page.getByRole('button', { name: '选择模型', exact: true }).click()
    await page.getByRole('button', { name: 'main-model', exact: true }).click()
    assert.ok(await page.getByRole('button', { name: '发送', exact: true }).isEnabled())
    await page.getByText('已经保存的回复', { exact: true }).waitFor()

    await openSettings()
    await page.getByRole('button', { name: '停用服务 主服务已编辑', exact: true }).click()
    await page.getByRole('button', { name: '启用服务 主服务已编辑', exact: true }).waitFor()
    await page.getByRole('button', { name: '停用服务 备用服务', exact: true }).click()
    await page.getByRole('button', { name: '启用服务 备用服务', exact: true }).waitFor()
    await closeSettings()
    assert.ok(await page.getByRole('button', { name: '选择模型', exact: true }).isDisabled())
    assert.ok(await page.getByRole('button', { name: '发送', exact: true }).isDisabled())
    await page.screenshot({ path: `${screenshots}/${width}-chat-provider-disabled.png` })
    assert.equal(calls.filter(call => call.path === '/agent-runs/stream').length, 0)
    assert.deepEqual(errors, [])
    console.log(`${width}px: provider disable/enable retry, disabled editing, session warning, model filtering and drafts passed`)
    await page.close()
  }
} finally { await browser.close() }
