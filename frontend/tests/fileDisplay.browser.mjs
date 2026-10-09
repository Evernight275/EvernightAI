import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';
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
    const html = `<!doctype html><html><head>
      <meta http-equiv="Content-Security-Policy" content="connect-src *">
      <link rel="stylesheet" href="https://charts.example.test/demo.css">
      <style>body{margin:0;padding:20px;font-family:sans-serif}h1{font-size:20px}
      canvas{width:100%;display:block}input{max-width:100%}section{padding:12px;border-radius:12px}</style>
      <script src="https://charts.example.test/demo.js"></script>
      </head><body><h1>交互分析图</h1><section id="chart-card">
      <label for="amplitude">振幅：<output id="amplitude-value">1</output></label>
      <input id="amplitude" type="range" min="1" max="3" value="1">
      <canvas id="chart" width="600" height="220"></canvas></section>
      <script>
        const slider = document.getElementById('amplitude');
        slider.oninput = () => {
          document.getElementById('amplitude-value').value = slider.value;
          renderChart(Number(slider.value));
        };
        renderChart(1);
        try { parent.document.body.dataset.compromised = 'true'; }
        catch { document.body.dataset.parentBlocked = 'true'; }
        try { localStorage.setItem('preview-secret', 'test'); }
        catch { document.body.dataset.storageBlocked = 'true'; }
        try { document.body.dataset.secret = parent.EVERNIGHTAI_API_KEY; }
        catch { document.body.dataset.credentialsBlocked = 'true'; }
        fetch('https://preview.example.test/denied')
          .catch(() => document.body.dataset.networkBlocked = 'true');
      </script></body></html>`;
    const chartScript = `window.renderChart = (value) => {
      const canvas = document.getElementById('chart');
      const ctx = canvas.getContext('2d');
      const scale = new Function('height', 'value', 'return height * value');
      ctx.clearRect(0, 0, 600, 220);
      ctx.fillStyle = '#6366f1';
      [30, 55, 40, 65].forEach((height, index) =>
        ctx.fillRect(30 + index * 140, 210 - scale(height, value), 100, scale(height, value)));
      canvas.dataset.value = String(value);
    };`;
    const ids = ['a', 'b', 'c', 'd'].map((char) => char.repeat(32));
    const artifacts = ids.map((artifact_id, index) => ({
      artifact_id,
      name: ['分析图.png', '结果.csv', '分析页面.html', '历史页面.html'][index],
      title: index === 0 ? '季度分析图' : null,
      mime_type: index === 0 ? 'image/png' : index === 1 ? 'text/csv' : 'text/html',
      preview_kind: index === 0 ? 'image' : index === 2 ? 'html' : 'none',
      size_bytes: index === 0 ? png.length : index === 1 ? 10 : Buffer.byteLength(html),
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
    let forbiddenRequests = 0;
    await page.route('https://charts.example.test/**', (route) => {
      assert.equal(route.request().headers()['x-evernight-api-key'], undefined);
      return route.fulfill({
        contentType: route.request().url().endsWith('.js') ? 'text/javascript' : 'text/css',
        body: route.request().url().endsWith('.js')
          ? chartScript
          : '#chart-card { background: #eef2ff; }',
      });
    });
    await page.route('https://preview.example.test/**', (route) => {
      forbiddenRequests++;
      return route.fulfill({ json: {} });
    });
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
          history: {
            started_at: new Date().toISOString(),
            message_offset: offset,
            message_indices: Array.from(
              { length: artifacts.length + 3 },
              (_, index) => offset + index,
            ),
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
            body: index === 0 ? png : index === 1 ? 'value\n123\n' : html,
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
    assert.equal(await page.locator('.chat-file-result').count(), artifacts.length);
    assert.equal(contentReads, 3, 'images and HTML should load previews; CSV should wait');
    const frames = page.locator('.chat-file-result iframe');
    assert.equal(await frames.count(), 2, 'new and historical HTML artifacts should preview');
    for (const iframe of await frames.all()) {
      assert.equal(await iframe.getAttribute('sandbox'), 'allow-scripts');
      assert.equal(await iframe.getAttribute('referrerpolicy'), 'no-referrer');
      assert.ok((await iframe.getAttribute('src')).startsWith('blob:'));
      const frame = iframe.contentFrame();
      await frame.locator('#chart[data-value="1"]').waitFor();
      await frame.locator('body[data-network-blocked="true"]').waitFor();
      assert.equal(await frame.locator('body').getAttribute('data-parent-blocked'), 'true');
      assert.equal(await frame.locator('body').getAttribute('data-storage-blocked'), 'true');
      assert.equal(await frame.locator('body').getAttribute('data-credentials-blocked'), 'true');
      assert.equal(
        await frame
          .locator('#chart-card')
          .evaluate((element) => getComputedStyle(element).backgroundColor),
        'rgb(238, 242, 255)',
      );
      await frame.getByRole('slider').press('ArrowRight');
      await frame.locator('#chart[data-value="2"]').waitFor();
      assert.equal(await frame.locator('#amplitude-value').textContent(), '2');
    }
    assert.equal(await page.locator('body').getAttribute('data-compromised'), null);
    assert.equal(forbiddenRequests, 0, 'HTML scripts must not make network data requests');
    for (let index = 0; index < artifacts.length; index++) {
      const downloaded = page.waitForEvent('download');
      await page
        .locator('.chat-file-result')
        .nth(index)
        .getByRole('button', { name: '下载文件', exact: true })
        .click();
      const download = await downloaded;
      assert.equal(download.suggestedFilename(), artifacts[index].name);
      if (index >= 2)
        assert.equal(await readFile(await download.path(), 'utf8'), html, 'download original HTML');
    }
    failRead = true;
    await page.reload();
    await page.getByRole('button', { name: '重新读取文件', exact: true }).first().waitFor();
    assert.equal(await page.locator('.chat-file-result').count(), artifacts.length);
    failRead = false;
    for (const card of await page.locator('.chat-file-result').all())
      await card.getByRole('button', { name: '重新读取文件', exact: true }).click();
    await page.waitForFunction(
      () => document.querySelector('.chat-file-result img')?.naturalWidth === 500,
    );
    await page
      .frameLocator('.chat-file-result iframe')
      .first()
      .locator('#chart[data-value="1"]')
      .waitFor();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.screenshot({ path: `/tmp/evernight-files/${width}-file-display.png` });
    await frames.first().scrollIntoViewIfNeeded();
    await page.screenshot({ path: `/tmp/evernight-files/${width}-html-preview.png` });
    const activeUrls = await page
      .locator('.chat-file-result img, .chat-file-result iframe')
      .evaluateAll((elements) => elements.map((element) => element.getAttribute('src')));
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('evernight-api-key-change')));
    await page.waitForFunction(
      (urls) => urls.every((url) => window.revokedFileUrls.includes(url)),
      activeUrls,
    );
    assert.deepEqual(errors, []);
    await page.close();
    console.log(
      `${width}px: image/HTML previews, isolated JavaScript, HTTPS libraries, downloads, history, retry and Blob cleanup passed`,
    );
  }
} finally {
  await browser.close();
}
