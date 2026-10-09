import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { chromium } from 'playwright';

const base = process.env.FRONTEND_URL || 'http://127.0.0.1:5173';
await mkdir('/tmp/evernight-images', { recursive: true });
const browser = await chromium.launch({ headless: true });
const content = (role, text) => ({ role, content: [{ type: 'text', text }] });
try {
  for (const width of [1440, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto('about:blank');
    const png = await page.evaluate(() => {
      const canvas = document.createElement('canvas');
      canvas.width = 320;
      canvas.height = 240;
      canvas.getContext('2d').fillRect(0, 0, 320, 240);
      return canvas.toDataURL('image/png').split(',')[1];
    });
    const runs = new Map();
    const records = new Map();
    const context = { context_id: 'ctx', messages: [], metadata: {} };
    const session = {
      session_id: 's',
      context_id: 'ctx',
      title: '图片工具测试',
      provider_id: 'p',
      model_id: 'chat',
    };
    let failImageRead = false;
    let directImagePosts = 0;
    await page.addInitScript(() => {
      window.EVERNIGHTAI_API_BASE = '/mock-api';
      window.imageToolRequests = [];
      window.imageToolResumes = [];
      const original = window.fetch;
      window.fetch = async (url, options) => {
        if (String(url).endsWith('/agent-runs/stream') || String(url).endsWith('/resume/stream')) {
          const body = JSON.parse(options.body);
          if (String(url).endsWith('/resume/stream')) window.imageToolResumes.push(body);
          else window.imageToolRequests.push(body);
          return new Response(
            new ReadableStream({
              start(controller) {
                window.emitImageToolEvents = (events) => {
                  for (const event of events)
                    controller.enqueue(
                      new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`),
                    );
                  controller.close();
                };
                options.signal?.addEventListener('abort', () =>
                  controller.error(new DOMException('Aborted', 'AbortError')),
                );
              },
            }),
            { headers: { 'content-type': 'text/event-stream' } },
          );
        }
        return original(url, options);
      };
    });
    await page.route('**/mock-api/**', async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname.replace('/mock-api', '');
      const json = (value) => route.fulfill({ json: value });
      if (path === '/health' || path === '/ready') return json({ status: 'ready' });
      if (path === '/providers') return json([{ provider_id: 'p', name: 'Test', type: 'openai' }]);
      if (path === '/providers/p/models') return json([{ model_id: 'chat' }]);
      if (path === '/tools')
        return json([
          {
            name: 'generate_image',
            description: 'Generate or edit images',
            requires_approval: true,
            parameters_schema: { type: 'object', properties: { prompt: { type: 'string' } } },
          },
        ]);
      if (path === '/sessions') return json([session]);
      if (path === '/sessions/s') return json(session);
      if (path === '/contexts/ctx') return json(context);
      if (path === '/agent-runs') return json([...runs.values()]);
      if (path.startsWith('/agent-runs/')) return json(runs.get(path.split('/')[2]));
      if (path.startsWith('/images') && request.method() === 'POST') directImagePosts++;
      if (path.startsWith('/images/records/')) {
        if (failImageRead)
          return route.fulfill({ status: 503, json: { error: { message: '图片暂时不可读取' } } });
        return json(records.get(path.split('/').at(-1)));
      }
      return json([]);
    });
    await page.goto(`${base}/chat.html`);
    if (width <= 760) await page.getByRole('button', { name: '会话管理', exact: true }).click();
    await page.getByRole('button', { name: '图片工具测试', exact: true }).click();
    assert.equal(await page.getByRole('button', { name: '图片创作', exact: true }).count(), 0);
    const ids = ['a'.repeat(32), 'b'.repeat(32)];
    for (let index = 0; index < 2; index++) {
      const prompt = index === 0 ? '帮我画一片叶子' : '把刚才的叶子改成蓝色';
      await page.locator('#chat-message').fill(prompt);
      await page.getByRole('button', { name: '发送', exact: true }).click();
      await page.waitForFunction((n) => window.imageToolRequests.length === n, index + 1);
      const request = await page.evaluate(() => window.imageToolRequests.at(-1));
      assert.ok(request.tools.some((tool) => tool.name === 'generate_image'));
      assert.equal(request.model_id, 'chat');
      const call = {
        tool_call_id: `image-${index}`,
        tool_call: {
          name: 'generate_image',
          arguments: {
            prompt,
            ...(index ? { references: [{ record_id: ids[0], image_index: 0 }] } : {}),
          },
        },
      };
      const response = {
        model_id: 'chat',
        message: { ...content('assistant', '正在准备图片。'), tool_calls: [call] },
      };
      const approval = {
        approval_id: `approve-${index}`,
        tool_call_id: call.tool_call_id,
        tool_name: 'generate_image',
        tool_call: call.tool_call,
        safety_level: 'sensitive',
        permissions: ['external_api', 'write'],
      };
      const trace = [
        { sequence: 1, event_type: 'chat_completed', response },
        { sequence: 2, event_type: 'tool_approval_requested', approval_request: approval },
        { sequence: 3, event_type: 'run_paused' },
      ];
      const run = {
        run_id: request.metadata.run_id,
        request,
        status: 'paused',
        trace,
        pending_approval_requests: [approval],
      };
      runs.set(run.run_id, run);
      await page.evaluate((events) => window.emitImageToolEvents(events), trace);
      const card = page.locator('.chat-tool-card').last();
      await card.getByRole('button', { name: '批准', exact: true }).click();
      await page.waitForFunction((n) => window.imageToolResumes.length === n, index + 1);
      assert.equal(
        await page.evaluate(() => window.imageToolResumes.at(-1).approvals[0].status),
        'approved',
      );
      const result = {
        type: 'image_generation',
        record_id: ids[index],
        images: [{ record_id: ids[index], image_index: 0, mime_type: 'image/png' }],
      };
      records.set(ids[index], {
        record_id: ids[index],
        provider_id: 'p',
        request: { prompt, model_id: 'image' },
        response: { model_id: 'image', images: [{ base64_data: png, mime_type: 'image/png' }] },
        created_at: new Date().toISOString(),
      });
      const finalResponse = {
        model_id: 'chat',
        message: content('assistant', `图片 ${index + 1} 已完成。`),
      };
      const events = [
        { sequence: 4, event_type: 'tool_started', tool_call: call },
        {
          sequence: 5,
          event_type: 'tool_completed',
          tool_call: call,
          tool_result: { tool_call_id: call.tool_call_id, tool_call_result: result },
        },
        { sequence: 6, event_type: 'chat_completed', response: finalResponse },
        { sequence: 7, event_type: 'run_stopped' },
      ];
      const offset = context.messages.length;
      context.messages.push(
        ...request.messages,
        response.message,
        content('tool', JSON.stringify(result)),
        finalResponse.message,
      );
      Object.assign(run, {
        status: 'finished',
        stop_reason: 'finished',
        response: finalResponse,
        trace: [...trace, ...events],
        pending_approval_requests: [],
        history: {
          started_at: `2026-10-04T08:00:0${index}Z`,
          message_offset: offset,
          message_indices: [offset, offset + 1, offset + 2, offset + 3],
        },
      });
      await page.evaluate((events) => window.emitImageToolEvents(events), events);
      await card.getByRole('img', { name: '工具生成图片 1', exact: true }).waitFor();
      await page.getByText(`图片 ${index + 1} 已完成。`, { exact: true }).waitFor();
      await card.getByLabel('工具图片 1 文件名', { exact: true }).fill('我的叶子');
      const downloaded = page.waitForEvent('download');
      await card.getByRole('button', { name: '下载图片 1', exact: true }).click();
      assert.equal((await downloaded).suggestedFilename(), '我的叶子.png');
    }
    failImageRead = true;
    await page.reload();
    await page.getByRole('button', { name: '重新读取图片', exact: true }).first().waitFor();
    assert.equal(await page.locator('.chat-image-result').count(), 2);
    failImageRead = false;
    for (const result of await page.locator('.chat-image-result').all())
      await result.getByRole('button', { name: '重新读取图片', exact: true }).click();
    await page.waitForFunction(
      () =>
        [...document.querySelectorAll('.chat-tool-images img')].length === 2 &&
        [...document.querySelectorAll('.chat-tool-images img')].every(
          (img) => img.complete && img.naturalWidth > 0,
        ),
    );
    assert.equal(directImagePosts, 0, 'tool previews must only read saved records');
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.screenshot({ path: `/tmp/evernight-images/${width}-image-tool.png` });
    assert.deepEqual(errors, []);
    await page.close();
  }
  console.log(
    'Image tool browser checks passed: approval, generation, follow-up edit, download, restored history and read retry at desktop/mobile widths.',
  );
} finally {
  await browser.close();
}
