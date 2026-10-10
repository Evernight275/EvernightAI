import assert from 'node:assert/strict';
import { chromium } from 'playwright';
import { mkdir } from 'node:fs/promises';

const base = process.env.FRONTEND_URL || 'http://127.0.0.1:5173';
await mkdir('/tmp/evernight-images', { recursive: true });
const browser = await chromium.launch({ headless: true });
try {
  for (const width of [1440, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto('about:blank');
    const bitmap = await page.evaluate(() => {
      const canvas = document.createElement('canvas');
      canvas.width = 320;
      canvas.height = 240;
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#217c61';
      ctx.fillRect(0, 0, 320, 240);
      return {
        png: canvas.toDataURL('image/png').split(',')[1],
        jpeg: canvas.toDataURL('image/jpeg').split(',')[1],
      };
    });
    const tasks = new Map();
    const records = new Map();
    const calls = [];
    let hold = true;
    let loseResponse = false;
    const provider = {
      provider_id: 'main',
      name: 'Images',
      type: 'openai',
      model: {
        chat: { model_id: 'chat-model', capabilities: ['chat'] },
        image: { model_id: 'image-model', capabilities: ['image_generation'] },
      },
    };
    function finish(task) {
      const id = task.body.task_id;
      records.set(id, {
        record_id: id,
        provider_id: 'main',
        request: task.body.request,
        response: {
          record_id: id,
          model_id: 'image-model',
          images: [{ base64_data: bitmap.png, mime_type: 'image/png' }],
        },
        created_at: task.summary.created_at,
      });
      task.summary.status = 'succeeded';
      task.summary.record_id = id;
    }
    await page.addInitScript(() => {
      window.EVERNIGHTAI_API_BASE = '/mock-api';
    });
    await page.route('**/mock-api/**', async (route) => {
      const req = route.request();
      const url = new URL(req.url());
      const path = url.pathname.replace('/mock-api', '');
      const json = (data, status = 200) => route.fulfill({ status, json: data });
      if (path === '/health' || path === '/ready') return json({ status: 'ready' });
      if (path === '/providers') return json([provider]);
      if (path === '/providers/main/models') return json(Object.values(provider.model));
      if (path === '/images/tasks' && req.method() === 'POST') {
        const body = req.postDataJSON();
        if (!tasks.has(body.task_id)) {
          calls.push(body);
          const task = {
            body,
            summary: {
              task_id: body.task_id,
              provider_id: 'main',
              model_id: body.request.model_id,
              prompt_preview: body.request.prompt,
              kind: body.request.images ? 'edit' : 'generate',
              session_id: body.session_id,
              status: 'running',
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
            },
          };
          tasks.set(body.task_id, task);
          if (!hold) finish(task);
        }
        if (loseResponse) {
          loseResponse = false;
          return route.abort('failed');
        }
        return json(tasks.get(body.task_id).summary, 202);
      }
      if (path === '/images/tasks') {
        const sessionId = url.searchParams.get('session_id');
        const all = [...tasks.values()]
          .filter((t) => !sessionId || t.body.session_id === sessionId)
          .map((t) => t.summary)
          .sort((a, b) => b.created_at.localeCompare(a.created_at));
        const offset = Number(url.searchParams.get('cursor') || 0);
        return json({
          items: all.slice(offset, offset + 20),
          next_cursor: all.length > offset + 20 ? String(offset + 20) : undefined,
        });
      }
      if (path.startsWith('/images/tasks/')) return json(tasks.get(path.split('/').at(-1)).summary);
      if (path === '/images/records') return json({ items: [] });
      if (path.startsWith('/images/records/')) return json(records.get(path.split('/').at(-1)));
      if (path.startsWith('/contexts/'))
        return json({ context_id: path.split('/')[2], messages: [] });
      if (path === '/agent-runs') return json([]);
      return json([]);
    });
    await page.goto(`${base}/chat.html#images`);
    await page.getByRole('option', { name: 'Images', exact: true }).waitFor({ state: 'attached' });
    await page.getByLabel('提示词', { exact: true }).fill('后台图片');
    await page.getByRole('button', { name: '生成图片', exact: true }).click();
    await page.getByRole('button', { name: '取消等待', exact: true }).waitFor();
    await page.reload();
    const taskList = page.getByRole('region', { name: '图片任务', exact: true });
    await taskList.getByText('正在生成', { exact: true }).waitFor();
    assert.equal(calls.length, 1, 'refresh must never resubmit a provider request');
    finish(tasks.get(calls[0].task_id));
    await taskList.getByRole('button', { name: '查看结果', exact: true }).waitFor();
    await taskList.getByRole('button', { name: '查看结果', exact: true }).click();
    await page.getByRole('img', { name: '生成图片 1', exact: true }).waitFor();
    for (let index = 0; index < 21; index++) {
      const id = index.toString(16).padStart(32, '0');
      tasks.set(id, {
        body: { task_id: id },
        summary: {
          task_id: id,
          provider_id: 'main',
          model_id: 'image-model',
          prompt_preview: `旧任务 ${index}`,
          kind: 'generate',
          status: 'failed',
          created_at: new Date(2020, 0, index + 1).toISOString(),
          updated_at: new Date().toISOString(),
        },
      });
    }
    await taskList.getByRole('button', { name: '刷新任务', exact: true }).click();
    await taskList.getByRole('button', { name: '加载更多任务', exact: true }).waitFor();
    await taskList.getByRole('button', { name: '加载更多任务', exact: true }).click();
    await taskList.getByText('旧任务 0', { exact: true }).waitFor();
    await taskList.getByRole('button', { name: '刷新任务', exact: true }).click();
    await taskList.getByText('旧任务 0', { exact: true }).waitFor();
    await page.getByRole('button', { name: '继续修改图片 1', exact: true }).click();
    await page.getByRole('img', { name: '参考图 1', exact: true }).waitFor();
    await page.getByRole('button', { name: '移除参考图 1', exact: true }).click();
    await page.getByLabel('上传参考图', { exact: true }).setInputFiles({
      name: 'reference.jpg',
      mimeType: 'image/jpeg',
      buffer: Buffer.from(bitmap.jpeg, 'base64'),
    });
    await page.getByRole('img', { name: '参考图 1', exact: true }).waitFor();
    await page.getByLabel('局部涂抹修改图 1').check();
    await page.getByLabel('修改要求', { exact: true }).fill('将涂抹部分改为蓝色');
    const submitEdit = page.getByRole('button', { name: '开始改图', exact: true });
    await page.waitForFunction(
      () => !document.querySelector('.image-page button[type=submit]').disabled,
    );
    await submitEdit.click();
    await page.getByRole('alert').filter({ hasText: '请先涂抹' }).waitFor();
    assert.equal(calls.length, 1, 'an empty mask must not submit');
    const canvas = page.getByLabel('涂抹修改区域', { exact: true });
    await canvas.scrollIntoViewIfNeeded();
    const rect = await canvas.boundingBox();
    await page.mouse.move(rect.x + rect.width / 2, rect.y + rect.height / 2);
    await page.mouse.down();
    await page.mouse.move(rect.x + rect.width * 0.55, rect.y + rect.height / 2, { steps: 4 });
    await page.mouse.up();
    hold = false;
    loseResponse = true;
    await submitEdit.click();
    await page.getByRole('alert').waitFor();
    assert.equal(calls.length, 2);
    await submitEdit.click();
    await page.getByText('已保存', { exact: true }).waitFor();
    assert.equal(calls.length, 2, 'retry after a lost response must reuse the task ID');
    const edit = calls[1].request;
    assert.equal(edit.images[0].mime_type, 'image/png');
    assert.equal(edit.mask.mime_type, 'image/png');
    const maskPixels = await page.evaluate(async (input) => {
      async function load(value) {
        const image = new Image();
        image.src = `data:image/png;base64,${value}`;
        await image.decode();
        return image;
      }
      const mask = await load(input.mask.base64_data);
      const original = await load(input.images[0].base64_data);
      const canvas = document.createElement('canvas');
      canvas.width = mask.width;
      canvas.height = mask.height;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(mask, 0, 0);
      return {
        size: [mask.width, mask.height, original.width, original.height],
        outside: ctx.getImageData(0, 0, 1, 1).data[3],
        inside: ctx.getImageData(160, 120, 1, 1).data[3],
      };
    }, edit);
    assert.deepEqual(maskPixels, { size: [320, 240, 320, 240], outside: 255, inside: 0 });
    await page.screenshot({ path: `/tmp/evernight-images/mask-${width}.png`, fullPage: true });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    assert.deepEqual(errors, []);
    await page.close();
  }
  console.log(
    'Background refresh, idempotent retry, mask pixels and pagination desktop/mobile checks passed',
  );
} finally {
  await browser.close();
}
