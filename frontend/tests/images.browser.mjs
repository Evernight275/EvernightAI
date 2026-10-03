import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { chromium } from 'playwright'

const base = process.env.FRONTEND_URL || 'http://127.0.0.1:5173'
const screenshots = process.env.SCREENSHOT_DIR || '/tmp/evernight-images'
await mkdir(screenshots, { recursive: true })
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH })
try {
  for (const width of [1440, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 900 }, acceptDownloads: true })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.goto('about:blank')
    const bitmap = await page.evaluate(() => {
      const canvas = document.createElement('canvas'); canvas.width = 640; canvas.height = 480
      const ctx = canvas.getContext('2d')
      ctx.fillStyle = '#e4f0ed'; ctx.fillRect(0, 0, 640, 480)
      ctx.fillStyle = '#217c61'; ctx.beginPath(); ctx.ellipse(320, 230, 160, 85, -0.6, 0, Math.PI * 2); ctx.fill()
      ctx.strokeStyle = '#154b3c'; ctx.lineWidth = 9; ctx.beginPath(); ctx.moveTo(170, 330); ctx.lineTo(460, 140); ctx.stroke()
      return canvas.toDataURL('image/png').split(',')[1]
    })
    const result = { model_id: 'manual-image', images: [{ base64_data: bitmap, mime_type: 'image/png', revised_prompt: 'A green leaf' }], usage: { input_tokens: 0, output_tokens: 12 } }
    let mode = 'success'
    let release
    let receivedCall
    const calls = []
    await page.addInitScript(() => { window.EVERNIGHTAI_API_BASE = '/mock-api' })
    await page.route('**/mock-api/**', async route => {
      const path = new URL(route.request().url()).pathname.replace('/mock-api', '')
      if (path === '/images/generations') {
        calls.push(route.request().postDataJSON())
        receivedCall?.()
        const currentMode = mode
        if (currentMode === 'failure') return route.fulfill({ status: 503, json: { error: { message: '生图服务暂时不可用' } } })
        if (currentMode === 'hold') await new Promise(resolve => { release = resolve })
        const response = currentMode === 'url' ? { ...result, images: [{ url: 'https://images.example/leaf.png' }] }
          : currentMode === 'multiple' ? { ...result, images: [result.images[0], result.images[0]] }
          : currentMode === 'hold' ? { ...result, model_id: 'late-response' } : result
        return route.fulfill({ json: response }).catch(() => {})
      }
      if (path === '/health' || path === '/ready') return route.fulfill({ json: { status: 'ready' } })
      if (path === '/images/records') return route.fulfill({ json: { items: [] } })
      if (path === '/providers') return route.fulfill({ json: [
        { provider_id: 'main', name: 'Image Provider', type: 'openai', model: { leaf: { model_id: 'declared-image', capabilities: ['image_generation'] } } },
        { provider_id: 'disabled', name: 'Disabled', type: 'openai', is_enabled: false },
        { provider_id: 'google', name: 'Google', type: 'google' },
      ] })
      return route.fulfill({ json: [] })
    })
    await page.route('https://images.example/leaf.png', route => {
      const headers = route.request().headers()
      assert.equal(headers.authorization, undefined)
      assert.equal(headers['x-evernight-api-key'], undefined)
      return route.fulfill({ contentType: 'image/png', body: Buffer.from(bitmap, 'base64') })
    })
    await page.goto(`${base}/images.html`)
    await page.getByRole('option', { name: 'Image Provider' }).waitFor({ state: 'attached' })
    assert.equal(await page.getByRole('option', { name: 'Disabled', exact: true }).count(), 0)
    await page.getByLabel('模型', { exact: true }).fill('manual-image')
    await page.getByLabel('提示词', { exact: true }).fill('一片清晰的绿色叶子')
    await page.getByRole('button', { name: '生成图片', exact: true }).click()
    const img = page.getByRole('img', { name: '生成图片 1', exact: true })
    await img.waitFor()
    await page.waitForFunction(() => document.querySelector('.image-preview img')?.naturalWidth > 0)
    assert.deepEqual(calls[0], { provider_id: 'main', request: { model_id: 'manual-image', prompt: '一片清晰的绿色叶子', count: 1, timeout_seconds: 180 } })
    assert.ok(await img.evaluate(image => image.naturalWidth === 640 && image.naturalHeight === 480))
    const pixels = await img.evaluate(image => {
      const canvas = document.createElement('canvas'); canvas.width = 640; canvas.height = 480
      const ctx = canvas.getContext('2d'); ctx.drawImage(image, 0, 0)
      return [Array.from(ctx.getImageData(0, 0, 1, 1).data), Array.from(ctx.getImageData(320, 230, 1, 1).data)]
    })
    assert.notDeepEqual(pixels[0], pixels[1])
    const downloaded = page.waitForEvent('download')
    await page.getByRole('button', { name: '下载图片 1', exact: true }).click()
    assert.equal((await downloaded).suggestedFilename(), 'evernight-image-1.png')
    await page.getByLabel('图片 1 文件名', { exact: true }).fill('绿色叶子.jpg')
    const customDownload = page.waitForEvent('download')
    await page.getByRole('button', { name: '下载图片 1', exact: true }).click()
    assert.equal((await customDownload).suggestedFilename(), '绿色叶子.png')
    await img.scrollIntoViewIfNeeded()
    await page.screenshot({ path: `${screenshots}/images-${width}.png`, fullPage: true })
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    mode = 'url'
    await page.getByRole('button', { name: '生成图片', exact: true }).click()
    await page.getByRole('link', { name: '打开原图 1', exact: true }).waitFor()
    assert.equal(await page.getByLabel('图片 1 文件名', { exact: true }).inputValue(), 'evernight-image-1')
    await page.getByLabel('图片 1 文件名', { exact: true }).fill('远程叶子')
    assert.equal(await page.getByRole('link', { name: '打开原图 1', exact: true }).getAttribute('rel'), 'noopener noreferrer')
    const urlDownload = page.waitForEvent('download')
    await page.getByRole('button', { name: '下载图片 1', exact: true }).click()
    assert.equal((await urlDownload).suggestedFilename(), '远程叶子.png')
    mode = 'failure'
    await page.getByRole('button', { name: '生成图片', exact: true }).click()
    await page.getByRole('alert').filter({ hasText: '生图服务暂时不可用' }).waitFor()
    assert.equal(await page.getByLabel('提示词', { exact: true }).inputValue(), '一片清晰的绿色叶子')
    assert.equal(await img.count(), 1)
    mode = 'hold'
    const heldRequest = new Promise(resolve => { receivedCall = resolve })
    await page.getByRole('button', { name: '生成图片', exact: true }).click()
    await heldRequest
    await page.waitForFunction(() => document.querySelector('button[type=submit]')?.disabled)
    assert.equal(calls.length, 4)
    await page.getByRole('button', { name: '取消等待', exact: true }).click()
    release()
    await page.getByRole('status').filter({ hasText: '已取消等待' }).waitFor()
    mode = 'success'
    await page.getByRole('button', { name: '生成图片', exact: true }).click()
    await page.getByRole('button', { name: '生成图片', exact: true }).waitFor()
    mode = 'hold'
    const identityRequest = new Promise(resolve => { receivedCall = resolve })
    await page.getByRole('button', { name: '生成图片', exact: true }).click()
    await identityRequest
    await page.getByRole('button', { name: '取消等待', exact: true }).waitFor()
    await page.waitForFunction(() => document.querySelector('button[type=submit]')?.disabled)
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('evernight-access-token-change')))
    release()
    await page.waitForFunction(() => document.querySelector('textarea')?.value === '')
    assert.equal(await img.count(), 0)
    assert.equal(await page.getByText('late-response', { exact: false }).count(), 0)
    assert.equal(await page.getByLabel('图片 1 文件名', { exact: true }).count(), 0)
    mode = 'multiple'
    await page.getByLabel('模型', { exact: true }).fill('manual-image')
    await page.getByLabel('提示词', { exact: true }).fill('两片绿色叶子')
    await page.getByLabel('数量', { exact: true }).fill('2')
    await page.getByRole('button', { name: '生成图片', exact: true }).click()
    await page.getByLabel('图片 2 文件名', { exact: true }).waitFor()
    for (const [index, name] of ['第一片叶子', '第二片叶子'].entries()) {
      await page.getByLabel(`图片 ${index + 1} 文件名`, { exact: true }).fill(name)
      const saved = page.waitForEvent('download')
      await page.getByRole('button', { name: `下载图片 ${index + 1}`, exact: true }).click()
      assert.equal((await saved).suggestedFilename(), `${name}.png`)
    }
    await page.getByLabel('图片 2 文件名', { exact: true }).fill('')
    const defaultDownload = page.waitForEvent('download')
    await page.getByRole('button', { name: '下载图片 2', exact: true }).click()
    assert.equal((await defaultDownload).suggestedFilename(), 'evernight-image-2.png')
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    assert.deepEqual(errors, [])
    await page.close()
  }
  console.log('Image generation and custom download filename desktop/mobile checks passed')
} finally { await browser.close() }
