import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { chromium } from 'playwright';

const base = process.env.FRONTEND_URL || 'http://127.0.0.1:5173';
const screenshots = process.env.SCREENSHOT_DIR || '/tmp/evernight-images';
await mkdir(screenshots, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
});
try {
  for (const width of [1440, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 900 }, acceptDownloads: true });
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto('about:blank');
    const bitmap = await page.evaluate(() => {
      const canvas = document.createElement('canvas');
      canvas.width = 640;
      canvas.height = 480;
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#e4f0ed';
      ctx.fillRect(0, 0, 640, 480);
      ctx.fillStyle = '#217c61';
      ctx.beginPath();
      ctx.ellipse(320, 230, 160, 85, -0.6, 0, Math.PI * 2);
      ctx.fill();
      return canvas.toDataURL('image/png').split(',')[1];
    });
    const records = new Map();
    let generations = 0;
    let mode = 'success';
    let failDelete = true;
    let releaseRead;
    let receivedRead;
    await page.addInitScript(() => {
      window.EVERNIGHTAI_API_BASE = '/mock-api';
      window.EVERNIGHTAI_API_KEY = 'alice';
    });
    const makeRecord = (id, prompt, owner = 'alice') => ({
      record_id: id,
      provider_id: 'main',
      owner_id: owner,
      created_at: new Date().toISOString(),
      request: {
        model_id: 'manual-image',
        prompt,
        count: 1,
        size: '1024x1024',
        quality: 'high',
        output_format: 'png',
        timeout_seconds: 180,
      },
      response: {
        record_id: id,
        model_id: 'manual-image',
        images: [{ base64_data: bitmap, mime_type: 'image/png' }],
      },
    });
    for (let index = 0; index < 21; index++)
      records.set(`seed-${index}`, makeRecord(`seed-${index}`, `历史图片 ${index}`));
    await page.route('**/mock-api/**', async (route) => {
      const path = new URL(route.request().url()).pathname.replace('/mock-api', '');
      const method = route.request().method();
      const owner = route.request().headers()['x-evernight-api-key'] || 'alice';
      if (path === '/health' || path === '/ready')
        return route.fulfill({ json: { status: 'ready' } });
      if (path === '/providers')
        return route.fulfill({
          json: [{ provider_id: 'main', name: 'Images', type: 'openai', model: {} }],
        });
      if (path === '/images/generations') {
        generations++;
        const request = route.request().postDataJSON().request;
        const record = makeRecord(`generated-${generations}`, request.prompt, owner);
        record.request = request;
        if (mode === 'save_failed')
          return route.fulfill({
            json: { ...record.response, record_id: undefined, persistence_warning: 'save_failed' },
          });
        records.set(record.record_id, record);
        return route.fulfill({ json: record.response });
      }
      if (path === '/images/records') {
        const offset = Number(new URL(route.request().url()).searchParams.get('cursor') || 0);
        const all = [...records.values()].filter((record) => record.owner_id === owner).reverse();
        return route.fulfill({
          json: {
            items: all.slice(offset, offset + 20).map((record) => ({
              record_id: record.record_id,
              provider_id: record.provider_id,
              model_id: record.request.model_id,
              prompt_preview: record.request.prompt,
              image_count: 1,
              created_at: record.created_at,
              archived: true,
            })),
            next_cursor: all.length > offset + 20 ? String(offset + 20) : undefined,
          },
        });
      }
      if (path.startsWith('/images/records/')) {
        const id = path.split('/').at(-1);
        const record = records.get(id);
        if (!record || record.owner_id !== owner)
          return route.fulfill({
            status: 404,
            json: { error: { message: 'Image record not found' } },
          });
        if (method === 'DELETE') {
          if (failDelete) {
            failDelete = false;
            return route.fulfill({ status: 503, json: { error: { message: '暂时无法删除' } } });
          }
          records.delete(id);
          return route.fulfill({ status: 204 });
        }
        if (mode === 'hold_read')
          await new Promise((resolve) => {
            releaseRead = resolve;
            receivedRead();
          });
        return route.fulfill({ json: record }).catch(() => {});
      }
      return route.fulfill({ json: [] });
    });
    await page.goto(`${base}/images.html`);
    await page.getByRole('button', { name: '查看生成记录 历史图片 20', exact: true }).waitFor();
    await page.getByRole('button', { name: '加载更多记录', exact: true }).click();
    await page.getByRole('button', { name: '查看生成记录 历史图片 0', exact: true }).waitFor();
    await page.getByLabel('模型', { exact: true }).fill('manual-image');
    await page.getByLabel('提示词', { exact: true }).fill('生成一片绿色叶子');
    await page.getByRole('button', { name: '生成图片', exact: true }).click();
    await page.getByText('已保存', { exact: true }).waitFor();
    await page
      .getByRole('button', { name: '查看生成记录 生成一片绿色叶子', exact: true })
      .waitFor();
    assert.equal(generations, 1);
    await page.reload();
    assert.equal(await page.getByRole('img', { name: '生成图片 1', exact: true }).count(), 0);
    await page.getByRole('button', { name: '查看生成记录 生成一片绿色叶子', exact: true }).click();
    const image = page.getByRole('img', { name: '生成图片 1', exact: true });
    await image.waitFor();
    await page.waitForFunction(
      () => document.querySelector('.image-preview img')?.naturalWidth === 640,
    );
    assert.equal(await page.getByLabel('提示词', { exact: true }).inputValue(), '生成一片绿色叶子');
    assert.equal(await page.getByLabel('模型', { exact: true }).inputValue(), 'manual-image');
    assert.equal(generations, 1, 'reading history must never call generation');
    await page.getByLabel('图片 1 文件名', { exact: true }).fill('历史绿叶');
    const download = page.waitForEvent('download');
    await page.getByRole('button', { name: '下载图片 1', exact: true }).click();
    assert.equal((await download).suggestedFilename(), '历史绿叶.png');
    await page.screenshot({ path: `${screenshots}/image-history-${width}.png`, fullPage: true });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.getByRole('button', { name: '删除生成记录 生成一片绿色叶子', exact: true }).click();
    await page.getByRole('button', { name: '删除记录', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: '暂时无法删除' }).waitFor();
    assert.equal(await image.count(), 1);
    await page.getByRole('button', { name: '删除记录', exact: true }).click();
    await page.waitForFunction(() => !document.querySelector('.chat-confirm-dialog')?.open);
    assert.equal(await image.count(), 0);
    assert.equal(records.has('generated-1'), false);
    mode = 'save_failed';
    await page.getByRole('button', { name: '生成图片', exact: true }).click();
    await page.getByRole('status').filter({ hasText: '保存失败' }).waitFor();
    assert.equal(await image.count(), 1);
    assert.equal(generations, 2);
    assert.equal(records.has('generated-2'), false);
    mode = 'hold_read';
    const held = new Promise((resolve) => {
      receivedRead = resolve;
    });
    await page.getByRole('button', { name: '查看生成记录 历史图片 20', exact: true }).click();
    await held;
    await page.evaluate(() => {
      localStorage.setItem('evernight.apiKey', 'bob');
      window.dispatchEvent(new CustomEvent('evernight-api-key-change'));
    });
    releaseRead();
    await page.getByText('暂无生成记录', { exact: true }).waitFor();
    assert.equal(await image.count(), 0);
    assert.equal(await page.getByLabel('提示词', { exact: true }).inputValue(), '');
    assert.equal(await page.getByRole('button', { name: /查看生成记录/ }).count(), 0);
    assert.equal(generations, 2);
    assert.deepEqual(errors, []);
    await page.close();
  }
  console.log(
    'Image history reload, pagination, preview, download, deletion, save failure and identity isolation passed',
  );
} finally {
  await browser.close();
}
