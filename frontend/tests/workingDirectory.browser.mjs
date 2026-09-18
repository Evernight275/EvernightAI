import assert from 'node:assert/strict'
import { chromium } from 'playwright'
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH })
try {
  for (const width of [1440, 390, 320]) {
    const page = await browser.newPage({ viewport: { width, height: 844 }, reducedMotion: 'reduce' })
    const errors = []
    page.on('pageerror', e => errors.push(e.message))
    await page.addInitScript(() => { window.EVERNIGHTAI_API_BASE = '/mock-api' })
    let created = false
    const listing = path => ({ root: '/workspace', path, truncated: false, entries: path === '.' ? [
      { name: 'project', path: 'project', is_directory: true },
      { name: 'README.md', path: 'README.md', is_directory: false },
    ] : path === 'project' && created ? [{ name: 'new', path: 'project/new', is_directory: true }] : [] })
    await page.route('**/mock-api/**', route => {
      const url = new URL(route.request().url())
      if (url.pathname.endsWith('/workspaces')) {
        if (route.request().method() === 'POST') {
          const body = route.request().postDataJSON()
          assert.equal(body.path, 'project')
          if (body.name === 'duplicate') return route.fulfill({ status: 409, json: { error: { message: '此名称已存在' } } })
          assert.equal(body.name, 'new')
          created = true
          return route.fulfill({ status: 201, json: listing('project/new') })
        }
        return route.fulfill({ json: listing(url.searchParams.get('path')) })
      }
      return route.fulfill({ json: url.pathname.endsWith('/health') ? { status: 'ok' } : [] })
    })
    await page.goto('http://127.0.0.1:5173/chat.html')
    const open = async () => {
      if (width <= 760) await page.getByRole('button', { name: '会话管理', exact: true }).click()
      await page.getByRole('button', { name: '选择工作文件夹' }).click()
    }
    await open()
    await page.getByText('README.md', { exact: true }).waitFor()
    await page.getByRole('button', { name: 'project', exact: true }).click()
    await page.getByText('此文件夹为空，可以作为新的工作目录。').waitFor()
    await page.getByRole('button', { name: '新建', exact: true }).click()
    await page.getByLabel('新文件夹名称').fill('duplicate')
    await page.getByRole('button', { name: '创建文件夹', exact: true }).click()
    await page.getByRole('alert').filter({ hasText: '此名称已存在' }).waitFor()
    await page.getByLabel('新文件夹名称').fill('new')
    await page.getByRole('button', { name: '创建文件夹', exact: true }).click()
    await page.locator('.workspace-picker-toolbar strong').filter({ hasText: 'project/new' }).waitFor()
    await page.screenshot({ path: `/tmp/evernight-layout/${width}-working-directory.png` })
    assert.ok(await page.locator('.workspace-picker-dialog').evaluate(el => el.scrollWidth <= el.clientWidth))
    await page.getByRole('button', { name: '使用此文件夹' }).click()
    assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem('evernight.workingDirectory')).path), 'project/new')
    await page.reload()
    if (width <= 760) await page.getByRole('button', { name: '会话管理', exact: true }).click()
    await page.getByRole('button', { name: '选择工作文件夹' }).filter({ hasText: 'new' }).waitFor()
    await page.getByRole('button', { name: '选择工作文件夹' }).click()
    await page.getByRole('button', { name: '上一级文件夹' }).click()
    await page.getByRole('button', { name: 'new', exact: true }).waitFor()
    await page.getByRole('button', { name: '使用此文件夹' }).click()
    assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem('evernight.workingDirectory')).path), 'project')
    assert.deepEqual(errors, [])
    await page.close()
    console.log(`${width}px: directory browse/create/conflict/switch/restore passed`)
  }
} finally { await browser.close() }
