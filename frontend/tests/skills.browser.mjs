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
    const skills = [
      { name: 'echo', description: 'Builtin', capabilities: ['agent'], is_enabled: true, is_template: false, input_schema: { type: 'object' } },
      { name: 'chat-only', description: 'Chat', capabilities: ['chat'], is_enabled: true },
      { name: 'disabled', description: 'Disabled', capabilities: ['agent'], is_enabled: false },
      { name: 'dependency', description: 'Missing tool', capabilities: ['agent'], is_enabled: true, required_tools: ['missing'] },
      { name: 'complex', description: 'Nested', capabilities: ['agent'], is_enabled: true, input_schema: { type: 'object', properties: { items: { type: 'array' } } } },
    ]
    const templates = new Map()
    const schema = { type: 'object', required: ['tone', 'flag'], properties: {
      tone: { type: 'string', title: '语气', enum: ['calm', 'concise'] },
      count: { type: 'integer', title: '数量', minimum: 1 },
      flag: { type: 'boolean', title: '严格模式' },
    } }
    let failSave = true
    let holdPreview = false
    let releasePreview
    let receivedPreview
    let pendingPreview
    page.on('pageerror', error => errors.push(error.message))
    await page.addInitScript(() => { window.EVERNIGHTAI_API_BASE = '/mock-api' })
    await page.route('**/mock-api/**', async route => {
      const path = new URL(route.request().url()).pathname.replace('/mock-api', '')
      const method = route.request().method()
      const data = method === 'GET' ? null : route.request().postDataJSON()
      calls.push({ path, method, data })
      const json = value => route.fulfill({ json: value })
      if (path === '/health' || path === '/ready') return json({ status: 'ready' })
      if (path === '/providers') return json([{ provider_id: 'main', name: 'Main', type: 'openai', is_enabled: true, model: { main: { model_id: 'model' } } }])
      if (path === '/providers/main/models') return json([{ model_id: 'model' }])
      if (path === '/skills' && method === 'GET') return json(skills)
      if (path === '/skills' && method === 'POST') {
        if (failSave) { failSave = false; return route.fulfill({ status: 503, json: { error: { message: '技能保存暂时失败' } } }) }
        if (templates.has(data.name)) return route.fulfill({ status: 409, json: { error: { message: '技能已存在' } } })
        templates.set(data.name, data)
        const { prompt, ...definition } = data
        skills.push({ ...definition, is_template: true })
        return route.fulfill({ status: 201, json: skills.at(-1) })
      }
      if (path.startsWith('/skills/')) {
        const name = path.split('/')[2]
        const skill = skills.find(skill => skill.name === name)
        if (path.endsWith('/template')) return json(templates.get(name))
        if (path.endsWith('/render')) {
          if (holdPreview) await new Promise(resolve => { releasePreview = resolve; receivedPreview() })
          const value = data.variables?.tone
          if (name === 'style' && !value) return route.fulfill({ status: 400, json: { error: { message: '技能参数缺少 tone' } } })
          return json({ skill_name: name, render_id: `${name}-0`, messages: [{ role: 'system', content: [{ type: 'text', text: `Use ${value || 'default'} style` }] }] })
        }
        if (method === 'PATCH') { Object.assign(skill, data); Object.assign(templates.get(name), data); return json(skill) }
        if (method === 'DELETE') { skills.splice(skills.indexOf(skill), 1); templates.delete(name); return route.fulfill({ status: 204 }) }
      }
      if (path === '/sessions') return json([{ session_id: 'session-1', context_id: 'ctx-1', title: '测试会话', provider_id: 'main', model_id: 'model' }])
      if (path === '/sessions/session-1') return json({ session_id: 'session-1', context_id: 'ctx-1', title: '测试会话', provider_id: 'main', model_id: 'model' })
      if (path === '/contexts/ctx-1') return json({ context_id: 'ctx-1', messages: [] })
      if (path === '/contexts/ctx-1/compose-preview') {
        if (holdPreview) await new Promise(resolve => { releasePreview = resolve; receivedPreview() })
        return json({ ...data })
      }
      return json([])
    })
    await page.goto(base)
    await page.getByRole('button', { name: '技能管理', exact: true }).click()
    assert.equal(await page.getByRole('button', { name: '编辑技能 echo', exact: true }).count(), 0)
    await page.getByRole('button', { name: '新建技能', exact: true }).click()
    await page.getByLabel('技能名称', { exact: true }).fill('style')
    await page.getByLabel('技能描述', { exact: true }).fill('风格技能')
    await page.getByLabel('提示词模板', { exact: true }).fill('Use $tone style')
    await page.getByLabel('参数 Schema（JSON）', { exact: true }).fill(JSON.stringify(schema))
    await page.getByRole('button', { name: '保存技能', exact: true }).click()
    await page.getByRole('alert').filter({ hasText: '技能保存暂时失败' }).waitFor()
    assert.equal(await page.getByLabel('技能名称', { exact: true }).inputValue(), 'style')
    await page.getByRole('button', { name: '保存技能', exact: true }).click()
    await page.getByRole('button', { name: '编辑技能 style', exact: true }).waitFor()
    await page.getByRole('button', { name: '预览技能 style', exact: true }).click()
    await page.getByRole('button', { name: '预览技能提示词', exact: true }).click()
    await page.getByRole('alert').filter({ hasText: '技能参数缺少 tone' }).waitFor()
    await page.getByLabel('语气', { exact: false }).selectOption(JSON.stringify('calm'))
    await page.getByRole('checkbox', { name: '数量', exact: true }).check()
    await page.getByRole('spinbutton', { name: '数量', exact: true }).fill('3')
    await page.getByRole('button', { name: '预览技能提示词', exact: true }).click()
    await page.getByText('Use calm style', { exact: true }).waitFor()
    const render = calls.filter(call => call.path === '/skills/style/render').at(-1)
    assert.deepEqual(render.data.variables, { flag: false, tone: 'calm', count: 3 })
    await page.getByLabel('语气', { exact: false }).selectOption(JSON.stringify('concise'))
    assert.equal(await page.getByText('Use calm style', { exact: true }).count(), 0)
    await page.getByRole('button', { name: '预览技能提示词', exact: true }).click()
    await page.getByText('Use concise style', { exact: true }).waitFor()
    await page.getByRole('button', { name: '编辑技能 style', exact: true }).click()
    assert.ok(await page.getByLabel('技能名称', { exact: true }).isDisabled())
    await page.getByLabel('技能描述', { exact: true }).fill('已编辑技能')
    await page.getByRole('button', { name: '保存技能', exact: true }).click()
    await page.getByText('已编辑技能', { exact: true }).waitFor()
    const download = page.waitForEvent('download')
    await page.getByRole('button', { name: '导出技能 style', exact: true }).click()
    assert.equal((await download).suggestedFilename(), 'style.json')
    await page.getByRole('button', { name: '停用 style', exact: true }).click()
    await page.getByRole('button', { name: '启用 style', exact: true }).waitFor()
    assert.ok(await page.getByRole('button', { name: '预览技能 style', exact: true }).isDisabled())
    await page.getByRole('button', { name: '启用 style', exact: true }).click()
    await page.getByRole('button', { name: '停用 style', exact: true }).waitFor()
    await page.getByLabel('导入技能模板', { exact: true }).setInputFiles({ name: 'import.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify({ name: 'imported', description: '导入的模板', prompt: 'Hello' })) })
    assert.equal(await page.getByLabel('技能名称', { exact: true }).inputValue(), 'imported')
    assert.equal(templates.has('imported'), false, 'import must wait for explicit save')
    await page.getByRole('button', { name: '保存技能', exact: true }).click()
    await page.getByRole('button', { name: '编辑技能 imported', exact: true }).waitFor()
    assert.ok(await page.locator('.settings-shell').evaluate(el => el.scrollWidth <= el.clientWidth))
    await page.screenshot({ path: `${screenshots}/${width}-skill-management.png` })
    await page.getByRole('button', { name: '删除技能 imported', exact: true }).click()
    await page.getByRole('button', { name: '取消', exact: true }).click()
    assert.equal(templates.has('imported'), true)
    await page.getByRole('button', { name: '删除技能 imported', exact: true }).click()
    await page.getByRole('button', { name: '确认删除技能', exact: true }).click()
    await page.getByRole('button', { name: '编辑技能 imported', exact: true }).waitFor({ state: 'hidden' })
    await page.goto(`${base}/chat.html`)
    if (width <= 760) await page.getByRole('button', { name: '会话管理', exact: true }).click()
    await page.getByRole('button', { name: '测试会话', exact: true }).click()
    await page.getByText('技能与上下文', { exact: true }).click()
    const choices = await page.getByLabel('本轮技能').locator('option').evaluateAll(elements => elements.map(element => element.value))
    assert.ok(!choices.includes('disabled') && !choices.includes('chat-only'))
    await page.getByLabel('本轮技能').selectOption('dependency')
    await page.getByRole('alert').filter({ hasText: '缺少必需工具：missing' }).waitFor()
    await page.locator('#chat-message').fill('草稿')
    assert.ok(await page.getByRole('button', { name: '发送', exact: true }).isDisabled())
    await page.getByLabel('本轮技能').selectOption('style')
    await page.getByLabel('语气', { exact: false }).selectOption(JSON.stringify('calm'))
    await page.getByRole('button', { name: '预览技能提示词', exact: true }).click()
    await page.getByText('Use calm style', { exact: true }).waitFor()
    assert.ok(await page.getByRole('button', { name: '发送', exact: true }).isEnabled())
    await page.screenshot({ path: `${screenshots}/${width}-skill-chat.png` })
    await page.getByLabel('本轮技能').selectOption('complex')
    await page.getByLabel('技能参数（JSON）').fill('{"items":[{"value":3}]}')
    await page.getByRole('button', { name: '预览上下文', exact: true }).click()
    await page.getByLabel('上下文预览').waitFor()
    assert.deepEqual(calls.filter(call => call.path.endsWith('/compose-preview')).at(-1).data.skills, [{ skill_name: 'complex', variables: { items: [{ value: 3 }] } }])
    holdPreview = true
    pendingPreview = new Promise(resolve => { receivedPreview = resolve })
    await page.getByRole('button', { name: '预览上下文', exact: true }).click()
    await pendingPreview
    await page.getByLabel('技能参数（JSON）').fill('{"items":[{"value":4}]}')
    const staleContext = page.waitForResponse(response => response.url().endsWith('/compose-preview'))
    releasePreview()
    await (await staleContext).finished()
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    assert.equal(await page.getByLabel('上下文预览').count(), 0, 'changed inputs must discard in-flight context previews')
    pendingPreview = new Promise(resolve => { receivedPreview = resolve })
    await page.getByRole('button', { name: '预览技能提示词', exact: true }).click()
    await pendingPreview
    await page.getByLabel('技能参数（JSON）').fill('{"items":[{"value":5}]}')
    const staleSkill = page.waitForResponse(response => response.url().endsWith('/render'))
    releasePreview()
    await (await staleSkill).finished()
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    assert.equal(await page.getByText('Use default style', { exact: true }).count(), 0, 'changed inputs must discard in-flight skill previews')
    assert.deepEqual(errors, [])
    console.log(`${width}px: skill create/retry, forms, previews, editing, enable/disable, export/import/delete, capability filtering and tool dependencies passed`)
    await page.close()
  }
} finally { await browser.close() }
