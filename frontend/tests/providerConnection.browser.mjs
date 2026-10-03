import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { chromium } from 'playwright';

const base = process.env.FRONTEND_URL || 'http://127.0.0.1:5173';
const screenshots = process.env.SCREENSHOT_DIR || '/tmp/evernight-layout';
await mkdir(screenshots, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
});
try {
  for (const width of [1440, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const errors = [];
    const calls = [];
    const providers = [
      {
        provider_id: 'main',
        name: '主服务',
        type: 'openai',
        is_enabled: true,
        model: { alias: { model_id: 'declared' } },
      },
      { provider_id: 'off', name: '停用服务', type: 'openai', is_enabled: false, model: {} },
    ];
    let release;
    let received;
    let pending = new Promise((resolve) => {
      received = resolve;
    });
    let mode = 'upstream';
    page.on('pageerror', (error) => errors.push(error.message));
    await page.addInitScript(() => {
      window.EVERNIGHTAI_API_BASE = '/mock-api';
    });
    await page.route('**/mock-api/**', async (route) => {
      const path = new URL(route.request().url()).pathname.replace('/mock-api', '');
      const method = route.request().method();
      const data = method === 'GET' ? null : route.request().postDataJSON();
      const json = (value) => route.fulfill({ json: value });
      if (path === '/providers') return json(providers);
      if (path === '/providers/main/models') return json(Object.values(providers[0].model));
      if (path === '/providers/main/config') return json({ ...providers[0], has_api_key: true });
      if (path === '/providers/main' && method === 'PATCH') {
        Object.assign(providers[0], data);
        return json(providers[0]);
      }
      if (path === '/providers/main/test') {
        calls.push(data);
        await new Promise((resolve) => {
          release = resolve;
          received();
        });
        if (mode === 'permission')
          return route.fulfill({ status: 403, json: { error: { message: '缺少连接测试权限' } } });
        return json({
          provider_id: 'main',
          model_id: data.model_id,
          elapsed_ms: 123,
          success: mode === 'success',
          ...(mode === 'success'
            ? { response_model_id: 'actual-model' }
            : { error_type: 'ProviderAuthorizationError', error_message: 'Credentials rejected' }),
        });
      }
      if (path === '/health' || path === '/ready') return json({ status: 'ready' });
      return json([]);
    });
    await page.goto(base);
    await page.getByRole('button', { name: '连接与认证', exact: true }).click();
    assert.ok(
      await page.getByRole('button', { name: '测试连接 停用服务', exact: true }).isDisabled(),
    );
    await page.getByRole('button', { name: '编辑服务 主服务', exact: true }).click();
    await page.getByLabel('服务名称', { exact: true }).fill('未保存名称');
    await page.getByRole('button', { name: '测试连接 主服务', exact: true }).click();
    assert.equal(calls.length, 0);
    const panel = page.getByRole('region', { name: '服务连接测试' });
    await panel.getByLabel('测试模型', { exact: true }).fill(' undeclared ');
    await panel.getByRole('button', { name: '开始测试', exact: true }).click();
    await pending;
    assert.ok(await panel.getByRole('button', { name: '正在测试…', exact: true }).isDisabled());
    assert.ok(await page.getByRole('button', { name: '保存服务', exact: true }).isDisabled());
    assert.deepEqual(calls, [{ model_id: 'undeclared' }]);
    release();
    await panel
      .getByText('上游服务拒绝了当前凭据，请检查服务密钥和访问权限。', { exact: true })
      .waitFor();
    mode = 'success';
    async function run() {
      pending = new Promise((resolve) => {
        received = resolve;
      });
      await panel.getByRole('button', { name: '开始测试', exact: true }).click();
      await pending;
      release();
    }
    await run();
    await panel.getByText('响应模型：actual-model', { exact: true }).waitFor();
    await panel.getByText('连接测试成功 · 123 ms（含模型生成）', { exact: true }).waitFor();
    assert.equal(calls.length, 2);
    assert.ok(
      await page.locator('.settings-shell').evaluate((el) => el.scrollWidth <= el.clientWidth),
    );
    await panel.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${screenshots}/${width}-provider-connection.png` });
    await panel.getByLabel('测试模型', { exact: true }).fill('another');
    assert.equal(await panel.getByLabel('连接测试结果').count(), 0);
    mode = 'permission';
    await run();
    await panel.getByRole('alert').filter({ hasText: '当前身份没有执行此操作的权限。' }).waitFor();
    await page.getByRole('button', { name: '保存服务', exact: true }).click();
    await panel.waitFor({ state: 'hidden' });
    await page.getByRole('button', { name: '测试连接 未保存名称', exact: true }).click();
    assert.equal(await panel.getByLabel('连接测试结果').count(), 0);
    assert.equal(calls.length, 3);
    assert.deepEqual(errors, []);
    console.log(
      `${width}px: saved-config test, undeclared model, busy guard, safe failure, retry, permission and result invalidation passed`,
    );
    await page.close();
  }
} finally {
  await browser.close();
}
