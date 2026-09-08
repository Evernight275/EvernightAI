import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { chromium } from 'playwright'
const base = process.env.FRONTEND_URL || 'http://127.0.0.1:5173'
const screenshots = process.env.SCREENSHOT_DIR || '/tmp/evernight-layout'
await mkdir(screenshots, { recursive: true })
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH })
try {
  for (const width of [1440, 390, 320]) {
    const page = await browser.newPage({ viewport: { width, height: 844 } })
    const errors = []
    page.on('pageerror', (error) => errors.push(error.message))
    await page.addInitScript(() => { window.EVERNIGHTAI_API_BASE = '/mock-api' })
    await page.route('**/mock-api/**', (route) => route.fulfill({ json: route.request().url().endsWith('/health') ? { status: 'ready' } : [] }))
    await page.goto(`${base}/chat.html`)
    await page.locator('#chat-message').fill('保留这份草稿')
    async function openSettings() {
      if (width <= 760) await page.getByRole('button', { name: '会话管理', exact: true }).click()
      await page.getByRole('button', { name: '设置', exact: true }).click()
      await page.locator('.settings-dialog').waitFor()
    }
    await openSettings()
    assert.ok(await page.locator('.settings-dialog').evaluate((el) => el.matches(':modal')))
    await page.screenshot({ path: `${screenshots}/${width}-settings-general.png` })
    await page.getByRole('button', { name: '连接与认证', exact: true }).click()
    await page.getByLabel('API Key', { exact: true }).fill('test-browser-key')
    await page.getByRole('button', { name: '保存', exact: true }).click()
    await page.getByText('API Key 已保存。', { exact: true }).waitFor()
    await page.getByRole('button', { name: '清除', exact: true }).click()
    await page.getByText('API Key 已清除。', { exact: true }).waitFor()
    await page.screenshot({ path: `${screenshots}/${width}-settings-auth.png` })
    await page.getByRole('button', { name: '数据控制', exact: true }).click()
    await page.getByRole('button', { name: '管理凭证', exact: true }).click()
    await page.getByLabel('API Key', { exact: true }).waitFor()
    assert.ok(await page.locator('.settings-shell').evaluate((el) => el.scrollWidth <= el.clientWidth))
    assert.ok(await page.locator('.settings-shell').evaluate((el) => el.getBoundingClientRect().bottom <= innerHeight))
    await page.keyboard.press('Escape')
    await page.waitForFunction(() => !document.querySelector('.settings-dialog').open)
    assert.equal(await page.locator('#chat-message').inputValue(), '保留这份草稿')
    await openSettings()
    await page.getByRole('button', { name: '关闭设置', exact: true }).click()
    await page.waitForFunction(() => !document.querySelector('.settings-dialog').open)
    await page.goto(base)
    await page.getByRole('button', { name: '连接与认证', exact: true }).click()
    await page.getByLabel('API Key', { exact: true }).waitFor()
    assert.equal(await page.getByRole('link', { name: '返回聊天', exact: true }).getAttribute('href'), '/chat.html')
    assert.deepEqual(errors, [])
    console.log(`${width}px: settings navigation, credentials, close/Escape, draft preservation and standalone entry passed`)
    await page.close()
  }
} finally { await browser.close() }
