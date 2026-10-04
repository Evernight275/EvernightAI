import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { chromium } from 'playwright';

const base = process.env.FRONTEND_URL || 'http://127.0.0.1:5173';
await mkdir('/tmp/evernight-tool-policies', { recursive: true });
const browser = await chromium.launch({ headless: true });
try {
  for (const width of [1440, 390, 320]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    const policies = new Map();
    const sessions = new Map();
    const contexts = new Map();
    const runs = new Map();
    const posted = [];
    let failSave = true;
    let slowSave = false;
    const definitions = [
      {
        name: 'read_text_file',
        description: '读取工作目录中的文件。',
        permissions: ['read', 'filesystem'],
        safety_level: 'safe',
        requires_approval: false,
      },
      {
        name: 'generate_image',
        description: '根据提示词生成图片，或修改已保存的图片。',
        permissions: ['external_api', 'write'],
        safety_level: 'sensitive',
        requires_approval: true,
      },
      {
        name: 'blocked_tool',
        description: '被服务器规则禁止的工具。',
        permissions: ['shell'],
        safety_level: 'restricted',
        requires_approval: true,
      },
    ];
    const defaultModes = ['allow', 'ask', 'deny'];
    function settings(owner) {
      return definitions.map((tool, index) => {
        const configured_mode = policies.get(`${owner}:${tool.name}`) ?? null;
        return {
          tool,
          mode: index === 2 ? 'deny' : (configured_mode ?? defaultModes[index]),
          default_mode: defaultModes[index],
          configured_mode,
          blocked_reason: index === 2 ? 'Blocked permissions: shell' : null,
        };
      });
    }
    await page.addInitScript(() => {
      window.EVERNIGHTAI_API_BASE = '/mock-api';
      localStorage.setItem('evernight.apiKey', 'alice-key');
    });
    await page.route('**/mock-api/**', async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname.replace('/mock-api', '');
      const owner = request.headers()['x-evernight-api-key']?.replace('-key', '') || 'alice';
      const json = (value) => route.fulfill({ json: value });
      if (path === '/auth/me')
        return json({
          authentication_enabled: true,
          principal: {
            principal_id: owner,
            principal_type: 'user',
            roles: [],
            permissions: owner === 'reader' ? ['tools:list'] : ['*'],
          },
        });
      if (path === '/health' || path === '/ready') return json({ status: 'ready' });
      if (path === '/providers') return json([{ provider_id: 'p', name: 'Test', type: 'openai' }]);
      if (path === '/providers/p/models') return json([{ model_id: 'chat' }]);
      if (path === '/tools')
        return json(
          settings(owner)
            .filter((setting) => setting.mode !== 'deny')
            .map((setting) => ({
              ...setting.tool,
              requires_approval: setting.mode === 'ask',
              approval_mode: setting.mode === 'ask' ? 'required' : 'never',
            })),
        );
      if (path === '/tools/policies') return json(settings(owner));
      if (path.endsWith('/policy')) {
        if (owner === 'reader')
          return route.fulfill({ status: 403, json: { error: { message: 'Permission denied' } } });
        if (failSave && request.method() === 'PUT') {
          failSave = false;
          return route.fulfill({ status: 503, json: { error: { message: '暂时无法保存' } } });
        }
        const name = decodeURIComponent(path.split('/')[2]);
        if (request.method() === 'DELETE') policies.delete(`${owner}:${name}`);
        else policies.set(`${owner}:${name}`, request.postDataJSON().mode);
        const saved = settings(owner).find((setting) => setting.tool.name === name);
        if (slowSave) await new Promise((resolve) => setTimeout(resolve, 500));
        return json(saved);
      }
      if (path === '/sessions' && request.method() === 'POST') {
        const session = request.postDataJSON();
        sessions.set(session.session_id, session);
        contexts.set(session.context_id, { context_id: session.context_id, messages: [] });
        return json(session);
      }
      if (path === '/sessions') return json([...sessions.values()]);
      if (path.startsWith('/sessions/')) return json(sessions.get(path.split('/')[2]));
      if (path.startsWith('/contexts/'))
        return json(
          contexts.get(path.split('/')[2]) || { context_id: path.split('/')[2], messages: [] },
        );
      if (path === '/agent-runs/stream') {
        const body = request.postDataJSON();
        posted.push(body);
        const response = {
          model_id: 'chat',
          message: { role: 'assistant', content: [{ type: 'text', text: '策略验证完成' }] },
        };
        const trace = [
          { sequence: 1, event_type: 'chat_completed', response },
          { sequence: 2, event_type: 'run_stopped' },
        ];
        runs.set(body.metadata.run_id, {
          run_id: body.metadata.run_id,
          request: body,
          status: 'finished',
          stop_reason: 'finished',
          response,
          trace,
        });
        return route.fulfill({
          contentType: 'text/event-stream',
          body: trace.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(''),
        });
      }
      if (path === '/agent-runs') return json([...runs.values()]);
      if (path.startsWith('/agent-runs/')) return json(runs.get(path.split('/')[2]));
      return json([]);
    });
    async function openSettings() {
      if (width <= 760) await page.getByRole('button', { name: '会话管理', exact: true }).click();
      await page.getByRole('button', { name: '设置', exact: true }).click();
      await page.getByRole('button', { name: '工具管理', exact: true }).click();
      await page.getByLabel('generate_image 使用策略', { exact: true }).waitFor();
    }
    const row = (name) => page.getByRole('form', { name: `${name} 权限设置`, exact: true });
    const select = (name) => page.getByLabel(`${name} 使用策略`, { exact: true });
    await page.goto(`${base}/chat.html`);
    await openSettings();
    await page.waitForFunction(
      () => !document.querySelector('[aria-label="generate_image 使用策略"]').disabled,
    );
    assert.equal(await select('generate_image').inputValue(), 'ask');
    assert.ok(await select('blocked_tool').isDisabled());
    await select('generate_image').selectOption('deny');
    await row('generate_image').getByRole('button', { name: '保存策略', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: '暂时无法保存' }).waitFor();
    assert.equal(
      await select('generate_image').inputValue(),
      'deny',
      'failed saves must retain draft',
    );
    assert.equal(policies.get('alice:generate_image'), undefined);
    await row('generate_image').getByRole('button', { name: '保存策略', exact: true }).click();
    await page.getByText('generate_image 已保存为“禁止”', { exact: true }).waitFor();
    await page.getByRole('button', { name: '关闭设置', exact: true }).click();
    await page.locator('#chat-message').fill('验证工具列表');
    await page.getByRole('button', { name: '发送', exact: true }).click();
    await page.getByText('策略验证完成', { exact: true }).waitFor();
    assert.ok(posted[0].tools.some((tool) => tool.name === 'read_text_file'));
    assert.ok(!posted[0].tools.some((tool) => tool.name === 'generate_image'));
    assert.ok(!posted[0].tools.some((tool) => tool.name === 'blocked_tool'));
    await page.reload();
    await openSettings();
    assert.equal(
      await select('generate_image').inputValue(),
      'deny',
      'server policy survives reload',
    );
    await select('generate_image').selectOption('allow');
    await row('generate_image').getByRole('button', { name: '保存策略', exact: true }).click();
    await page.getByText('generate_image 已保存为“允许”', { exact: true }).waitFor();
    await row('generate_image').getByRole('button', { name: '恢复默认', exact: true }).click();
    await page.getByText('generate_image 已恢复默认设置', { exact: true }).waitFor();
    assert.equal(await select('generate_image').inputValue(), 'ask');
    await select('read_text_file').selectOption('ask');
    await row('read_text_file').getByRole('button', { name: '保存策略', exact: true }).click();
    await page.getByText('read_text_file 已保存为“每次询问”', { exact: true }).waitFor();
    await select('generate_image').selectOption('deny');
    await row('generate_image').getByRole('button', { name: '保存策略', exact: true }).click();
    await page.getByText('generate_image 已保存为“禁止”', { exact: true }).waitFor();
    await page.getByRole('button', { name: '连接与认证', exact: true }).click();
    await page.getByLabel('API Key', { exact: true }).fill('bob-key');
    await page.getByRole('button', { name: '验证并保存', exact: true }).click();
    await page.getByText('身份已验证，访问凭证已保存。', { exact: true }).waitFor();
    await page.getByRole('button', { name: '工具管理', exact: true }).click();
    await select('generate_image').waitFor();
    assert.equal(
      await select('generate_image').inputValue(),
      'ask',
      'another user inherits its own defaults',
    );
    assert.equal(await select('read_text_file').inputValue(), 'allow');
    slowSave = true;
    await select('generate_image').selectOption('allow');
    const mutation = page.waitForRequest(
      (request) =>
        request.method() === 'PUT' && request.url().endsWith('/tools/generate_image/policy'),
    );
    await row('generate_image').getByRole('button', { name: '保存策略', exact: true }).click();
    await mutation;
    await page.evaluate(() => {
      localStorage.setItem('evernight.apiKey', 'reader-key');
      window.dispatchEvent(new Event('evernight-api-key-change'));
    });
    await page
      .getByText('当前账户可查看设置，修改需要 tools:configure 权限。', { exact: true })
      .waitFor();
    assert.ok(await select('generate_image').isDisabled());
    assert.equal(await select('generate_image').inputValue(), 'ask');
    assert.equal(
      await page.getByText('generate_image 已保存为“允许”', { exact: true }).count(),
      0,
      'stale mutation must not update a new identity',
    );
    assert.equal(policies.get('reader:generate_image'), undefined);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    if (width <= 640) {
      const description = await row('read_text_file')
        .locator('.tool-policy-description')
        .boundingBox();
      const controls = await row('read_text_file').locator('.tool-policy-controls').boundingBox();
      assert.ok(
        controls.y - (description.y + description.height) <= 24,
        'mobile controls must stay aligned with the tool description',
      );
    }
    await page.screenshot({ path: `/tmp/evernight-tool-policies/${width}-tool-settings.png` });
    assert.deepEqual(errors, []);
    await page.close();
  }
  console.log(
    'Tool policy browser checks passed: modes, reset, persistence, failed-save retry, chat catalog filtering, account isolation and stale mutation at desktop/mobile widths.',
  );
} finally {
  await browser.close();
}
