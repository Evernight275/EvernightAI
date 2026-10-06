import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { chromium } from 'playwright';

const base = process.env.FRONTEND_URL || 'http://127.0.0.1:5173';
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
});
await mkdir('/tmp/evernight-files', { recursive: true });
const message = (role, text) => ({ role, content: [{ type: 'text', text }] });
try {
  for (const width of [1440, 390, 320]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto('about:blank');
    const png = Buffer.from(
      await page.evaluate(() => {
        const canvas = document.createElement('canvas');
        canvas.width = 500;
        canvas.height = 280;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#f4f6ff';
        ctx.fillRect(0, 0, 500, 280);
        ctx.strokeStyle = '#6a5acd';
        ctx.lineWidth = 4;
        ctx.beginPath();
        ctx.moveTo(40, 240);
        ctx.lineTo(170, 120);
        ctx.lineTo(300, 180);
        ctx.lineTo(450, 40);
        ctx.stroke();
        return canvas.toDataURL('image/png').split(',')[1];
      }),
      'base64',
    );
    const ids = ['a'.repeat(32), 'b'.repeat(32)];
    const artifacts = ids.map((artifact_id, index) => ({
      artifact_id,
      name: index === 0 ? '分析图.png' : '结果.csv',
      title: index === 0 ? '季度分析图' : null,
      mime_type: index === 0 ? 'image/png' : 'text/csv',
      preview_kind: index === 0 ? 'image' : 'none',
      size_bytes: index === 0 ? png.length : 10,
      created_at: new Date().toISOString(),
    }));
    const session = {
      session_id: 's',
      context_id: 'ctx',
      title: '文件展示测试',
      provider_id: 'p',
      model_id: 'chat',
    };
    const context = { context_id: 'ctx', messages: [], metadata: {} };
    let run;
    let failRead = false;
    let contentReads = 0;
    await page.addInitScript(() => {
      window.EVERNIGHTAI_API_BASE = '/mock-api';
      window.EVERNIGHTAI_API_KEY = 'alice';
      window.fileObjectUrls = [];
      window.revokedFileUrls = [];
      const create = URL.createObjectURL.bind(URL);
      const revoke = URL.revokeObjectURL.bind(URL);
      URL.createObjectURL = (blob) => {
        const url = create(blob);
        window.fileObjectUrls.push(url);
        return url;
      };
      URL.revokeObjectURL = (url) => {
        window.revokedFileUrls.push(url);
        revoke(url);
      };
    });
    await page.route('**/mock-api/**', (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname.replace('/mock-api', '');
      const json = (value) => route.fulfill({ json: value });
      if (path === '/health' || path === '/ready') return json({ status: 'ready' });
      if (path === '/providers') return json([{ provider_id: 'p', name: 'Test', type: 'openai' }]);
      if (path === '/providers/p/models') return json([{ model_id: 'chat' }]);
      if (path === '/tools')
        return json([
          {
            name: 'display_file',
            description: 'Display a file',
            parameters_schema: { type: 'object', properties: { path: { type: 'string' } } },
          },
        ]);
      if (path === '/sessions') return json([session]);
      if (path === '/sessions/s') return json(session);
      if (path === '/contexts/ctx') return json(context);
      if (path === '/agent-runs') return json(run ? [run] : []);
      if (path === '/agent-runs/stream') {
        const body = request.postDataJSON();
        const calls = artifacts.map((artifact, index) => ({
          tool_call_id: `file-${index}`,
          tool_call: { name: 'display_file', arguments: { path: artifact.name } },
        }));
        const response = {
          model_id: 'chat',
          message: message('assistant', '图表和结果文件已展示。'),
        };
        const trace = [
          {
            event_type: 'chat_completed',
            response: { model_id: 'chat', message: { role: 'assistant', tool_calls: calls } },
          },
          ...calls.flatMap((tool_call, index) => [
            { event_type: 'tool_started', tool_call },
            {
              event_type: 'tool_completed',
              tool_call,
              tool_result: {
                tool_call_id: tool_call.tool_call_id,
                tool_call_result: { type: 'file_display', ...artifacts[index] },
              },
            },
          ]),
          { event_type: 'chat_completed', response },
          { event_type: 'run_stopped' },
        ].map((event, index) => ({ ...event, sequence: index + 1 }));
        const offset = context.messages.length;
        context.messages.push(
          ...body.messages,
          { role: 'assistant', tool_calls: calls },
          ...artifacts.map((artifact) =>
            message('tool', JSON.stringify({ type: 'file_display', ...artifact })),
          ),
          response.message,
        );
        run = {
          run_id: body.metadata.run_id,
          request: body,
          status: 'finished',
          stop_reason: 'finished',
          response,
          trace,
          pending_approval_requests: [],
          metadata: {
            agent_runtime: {
              history_started_at: new Date().toISOString(),
              context_message_offset: offset,
              context_message_indices: [offset, offset + 1, offset + 2, offset + 3, offset + 4],
            },
          },
        };
        return route.fulfill({
          contentType: 'text/event-stream',
          body: trace.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(''),
        });
      }
      if (path.startsWith('/agent-runs/')) return json(run);
      if (path.startsWith('/files/')) {
        assert.equal(request.headers()['x-evernight-api-key'], 'alice');
        assert.equal(url.searchParams.has('api_key'), false);
        if (failRead)
          return route.fulfill({ status: 503, json: { error: { message: '文件暂时不可读取' } } });
        const index = ids.indexOf(path.split('/')[2]);
        assert.ok(index >= 0);
        if (path.endsWith('/content')) {
          contentReads++;
          return route.fulfill({
            contentType: artifacts[index].mime_type,
            body: index === 0 ? png : 'value\n123\n',
          });
        }
        return json(artifacts[index]);
      }
      return json([]);
    });
    await page.goto(`${base}/chat.html`);
    if (width <= 760) await page.getByRole('button', { name: '会话管理', exact: true }).click();
    await page.getByRole('button', { name: '文件展示测试', exact: true }).click();
    await page.locator('#chat-message').fill('生成图表和 CSV 并展示');
    await page.getByRole('button', { name: '发送', exact: true }).click();
    await page.getByText('图表和结果文件已展示。', { exact: true }).waitFor();
    await page.waitForFunction(
      () => document.querySelector('.chat-file-result img')?.naturalWidth === 500,
    );
    assert.equal(await page.locator('.chat-file-result').count(), 2);
    assert.equal(contentReads, 1, 'non-image files should only be fetched when downloaded');
    for (let index = 0; index < artifacts.length; index++) {
      const downloaded = page.waitForEvent('download');
      await page
        .locator('.chat-file-result')
        .nth(index)
        .getByRole('button', { name: '下载文件', exact: true })
        .click();
      assert.equal((await downloaded).suggestedFilename(), artifacts[index].name);
    }
    failRead = true;
    await page.reload();
    await page.getByRole('button', { name: '重新读取文件', exact: true }).first().waitFor();
    assert.equal(await page.locator('.chat-file-result').count(), 2);
    failRead = false;
    for (const card of await page.locator('.chat-file-result').all())
      await card.getByRole('button', { name: '重新读取文件', exact: true }).click();
    await page.waitForFunction(
      () => document.querySelector('.chat-file-result img')?.naturalWidth === 500,
    );
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.screenshot({ path: `/tmp/evernight-files/${width}-file-display.png` });
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('evernight-api-key-change')));
    await page.waitForFunction(() => window.revokedFileUrls.length > 0);
    assert.deepEqual(errors, []);
    await page.close();
    console.log(
      `${width}px: file stream preview, authenticated downloads, history restore, retry and Blob cleanup passed`,
    );
  }
} finally {
  await browser.close();
}
