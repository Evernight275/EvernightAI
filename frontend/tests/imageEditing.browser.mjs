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
    const bitmaps = await page.evaluate(() => {
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
      const originals = Object.fromEntries(
        ['png', 'jpeg', 'webp'].map((format) => [
          format,
          canvas.toDataURL(`image/${format}`).split(',')[1],
        ]),
      );
      ctx.fillStyle = '#3877c4';
      ctx.beginPath();
      ctx.ellipse(320, 230, 160, 85, -0.6, 0, Math.PI * 2);
      ctx.fill();
      return { originals, result: canvas.toDataURL('image/png').split(',')[1] };
    });
    const calls = [];
    let record = null;
    let mode = 'success';
    let release;
    let receivedCall;
    await page.addInitScript(() => {
      window.EVERNIGHTAI_API_BASE = '/mock-api';
    });
    await page.route('**/mock-api/**', async (route) => {
      const path = new URL(route.request().url()).pathname.replace('/mock-api', '');
      if (path === '/health' || path === '/ready')
        return route.fulfill({ json: { status: 'ready' } });
      if (path === '/providers')
        return route.fulfill({
          json: [{ provider_id: 'main', name: 'Images', type: 'openai', model: {} }],
        });
      if (path === '/images/edits' || path === '/images/generations') {
        const body = route.request().postDataJSON();
        calls.push({ path, body });
        receivedCall?.();
        const current = mode;
        if (current === 'failure')
          return route.fulfill({ status: 400, json: { error: { message: '当前模型不支持改图' } } });
        if (current === 'hold')
          await new Promise((resolve) => {
            release = resolve;
          });
        const response = {
          record_id: 'edited-1',
          model_id: body.request.model_id,
          images: [{ base64_data: bitmaps.result, mime_type: 'image/png' }],
        };
        record = {
          record_id: 'edited-1',
          provider_id: body.provider_id,
          request: body.request,
          response,
          created_at: new Date().toISOString(),
        };
        return route.fulfill({ json: response }).catch(() => {});
      }
      if (path === '/images/records')
        return route.fulfill({
          json: {
            items: record
              ? [
                  {
                    record_id: record.record_id,
                    provider_id: record.provider_id,
                    model_id: record.request.model_id,
                    prompt_preview: record.request.prompt,
                    image_count: 1,
                    created_at: record.created_at,
                    archived: true,
                  },
                ]
              : [],
          },
        });
      if (path === '/images/records/edited-1') {
        if (route.request().method() === 'DELETE') {
          record = null;
          return route.fulfill({ status: 204 });
        }
        return route.fulfill({ json: record });
      }
      return route.fulfill({ json: [] });
    });
    await page.goto(`${base}/images.html`);
    await page.getByRole('option', { name: 'Images', exact: true }).waitFor({ state: 'attached' });
    await page.getByRole('button', { name: '上传改图', exact: true }).click();
    await page.getByLabel('模型', { exact: true }).fill('edit-model');
    await page.getByLabel('修改要求', { exact: true }).fill('保留叶子的形状，把绿色改为蓝色');
    const submit = page.getByRole('button', { name: '开始改图', exact: true });
    assert.equal(await submit.isDisabled(), true);
    const upload = page.getByLabel('上传参考图', { exact: true });
    const choosing = page.waitForEvent('filechooser');
    await page.getByRole('button', { name: '选择图片', exact: true }).click();
    await (
      await choosing
    ).setFiles({ name: '不支持.svg', mimeType: 'image/svg+xml', buffer: Buffer.from('<svg />') });
    await page.getByRole('alert').filter({ hasText: '图片内容不是 PNG、JPEG 或 WebP' }).waitFor();
    assert.equal(await submit.isDisabled(), true);
    await upload.setInputFiles({
      name: '损坏.png',
      mimeType: 'image/png',
      buffer: Buffer.from('invalid'),
    });
    await page.getByRole('alert').filter({ hasText: '图片内容不是 PNG、JPEG 或 WebP' }).waitFor();
    await upload.setInputFiles({
      name: '无法解码.png',
      mimeType: 'image/png',
      buffer: Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    });
    await page.getByRole('alert').filter({ hasText: '图片无法打开' }).waitFor();
    assert.equal(calls.length, 0);
    const file = (format, name = `参考图.${format}`) => ({
      name,
      mimeType: `image/${format}`,
      buffer: Buffer.from(bitmaps.originals[format], 'base64'),
    });
    const references = page.locator('.image-reference-grid img');
    const waitForCount = (count) =>
      page.waitForFunction(
        (count) => document.querySelectorAll('.image-reference-grid img').length === count,
        count,
      );
    const originalImages = Object.entries(bitmaps.originals).map(([format, bitmap]) => ({
      base64_data: bitmap,
      mime_type: `image/${format}`,
    }));
    for (const [name, reportedMime, actualFormat] of [
      ['下载图片.png', 'image/png', 'jpeg'],
      ['另一张图片.png', 'image/png', 'webp'],
      ['原图.jpg', 'image/jpeg', 'png'],
      ['未识别类型.bin', '', 'png'],
    ]) {
      await upload.setInputFiles({
        name,
        mimeType: reportedMime,
        buffer: Buffer.from(bitmaps.originals[actualFormat], 'base64'),
      });
      await waitForCount(1);
      await submit.click();
      await page.getByRole('button', { name: '开始改图', exact: true }).waitFor();
      const image = calls.at(-1).body.request.images[0];
      assert.equal(image.mime_type, `image/${actualFormat}`);
      assert.equal(
        image.base64_data,
        bitmaps.originals[actualFormat],
        'format detection must preserve the original bitmap bytes',
      );
      assert.equal(
        await references.nth(0).getAttribute('src'),
        `data:image/${actualFormat};base64,${image.base64_data}`,
      );
      await page.getByRole('button', { name: '移除参考图 1', exact: true }).click();
      await waitForCount(0);
    }
    calls.length = 0;
    record = null;
    await page.reload();
    await page.getByRole('option', { name: 'Images', exact: true }).waitFor({ state: 'attached' });
    await page.getByRole('button', { name: '上传改图', exact: true }).click();
    await page.getByLabel('模型', { exact: true }).fill('edit-model');
    await page.getByLabel('修改要求', { exact: true }).fill('保留叶子的形状，把绿色改为蓝色');
    await upload.setInputFiles([file('png'), file('jpeg'), file('webp')]);
    await waitForCount(3);
    for (const [index, image] of originalImages.entries())
      assert.equal(
        await references.nth(index).getAttribute('src'),
        `data:${image.mime_type};base64,${image.base64_data}`,
      );
    await page.getByRole('button', { name: '移除参考图 2', exact: true }).click();
    await waitForCount(2);
    assert.equal(
      await references.nth(1).getAttribute('src'),
      `data:image/webp;base64,${bitmaps.originals.webp}`,
    );
    await page.getByRole('button', { name: '前移参考图 2', exact: true }).click();
    assert.equal(
      await references.nth(0).getAttribute('src'),
      `data:image/webp;base64,${bitmaps.originals.webp}`,
    );
    await page.getByRole('button', { name: '后移参考图 1', exact: true }).click();
    assert.equal(
      await references.nth(0).getAttribute('src'),
      `data:image/png;base64,${bitmaps.originals.png}`,
    );
    await upload.setInputFiles(file('jpeg'));
    await waitForCount(3);
    await upload.setInputFiles([
      file('png'),
      { name: '损坏.png', mimeType: 'image/png', buffer: Buffer.from('invalid') },
    ]);
    await page.getByRole('alert').filter({ hasText: '图片内容不是 PNG、JPEG 或 WebP' }).waitFor();
    assert.equal(
      await references.count(),
      3,
      'failed batches must preserve the existing images without adding partial inputs',
    );
    await upload.setInputFiles(
      Array.from({ length: 14 }, (_, index) => file('png', `多余图片-${index}.png`)),
    );
    await page.getByRole('alert').filter({ hasText: '最多上传 16 张参考图' }).waitFor();
    assert.equal(await references.count(), 3);
    await upload.setInputFiles(
      Array.from({ length: 13 }, (_, index) => file('png', `参考图-${index + 4}.png`)),
    );
    await waitForCount(16);
    assert.equal(
      await page.getByRole('button', { name: '继续添加图片', exact: true }).isDisabled(),
      true,
    );
    assert.equal(
      await page.getByRole('button', { name: '后移参考图 16', exact: true }).isDisabled(),
      true,
    );
    await page.getByRole('button', { name: '移除参考图 16', exact: true }).click();
    await waitForCount(15);
    assert.equal(
      await page.getByRole('button', { name: '继续添加图片', exact: true }).isDisabled(),
      false,
    );
    await upload.setInputFiles(file('png'));
    await waitForCount(16);
    const submittedImages = [
      originalImages[0],
      originalImages[2],
      originalImages[1],
      ...Array(13).fill(originalImages[0]),
    ];
    await submit.click();
    await page.getByText('已保存', { exact: true }).waitFor();
    assert.equal(calls.length, 1);
    assert.equal(calls[0].path, '/images/edits');
    assert.deepEqual(calls[0].body, {
      provider_id: 'main',
      request: {
        model_id: 'edit-model',
        prompt: '保留叶子的形状，把绿色改为蓝色',
        count: 1,
        timeout_seconds: 180,
        images: submittedImages,
      },
    });
    for (let count = 16; count > 3; count--)
      await page.getByRole('button', { name: `移除参考图 ${count}`, exact: true }).click();
    await waitForCount(3);
    assert.equal(
      await page.getByRole('img', { name: '生成图片 1', exact: true }).getAttribute('src'),
      `data:image/png;base64,${bitmaps.result}`,
    );
    await page.getByLabel('图片 1 文件名', { exact: true }).fill('蓝色叶子');
    const download = page.waitForEvent('download');
    await page.getByRole('button', { name: '下载图片 1', exact: true }).click();
    assert.equal((await download).suggestedFilename(), '蓝色叶子.png');
    await page.screenshot({ path: `${screenshots}/image-editing-${width}.png`, fullPage: true });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    mode = 'failure';
    await submit.click();
    await page.getByRole('alert').filter({ hasText: '当前模型不支持改图' }).waitFor();
    assert.equal(await references.count(), 3);
    assert.equal(await page.getByRole('img', { name: '生成图片 1', exact: true }).count(), 1);
    assert.equal(calls.length, 2);
    await page.reload();
    await page
      .getByRole('button', { name: '查看生成记录 保留叶子的形状，把绿色改为蓝色', exact: true })
      .click();
    await waitForCount(16);
    assert.equal(
      await page
        .getByRole('button', { name: '上传改图', exact: true })
        .getAttribute('aria-pressed'),
      'true',
    );
    assert.equal(
      await page.getByLabel('修改要求', { exact: true }).inputValue(),
      '保留叶子的形状，把绿色改为蓝色',
    );
    assert.deepEqual(
      await references.evaluateAll((images) => images.map((image) => image.src)),
      submittedImages.map((image) => `data:${image.mime_type};base64,${image.base64_data}`),
    );
    assert.equal(calls.length, 2, 'restoring an edit must not call the provider');
    await page
      .getByRole('button', { name: '删除生成记录 保留叶子的形状，把绿色改为蓝色', exact: true })
      .click();
    await page.getByRole('button', { name: '删除记录', exact: true }).click();
    await page.getByRole('img', { name: '参考图 1', exact: true }).waitFor({ state: 'detached' });
    assert.equal(await page.getByRole('img', { name: '生成图片 1', exact: true }).count(), 0);
    assert.equal(await submit.isDisabled(), true);
    record = {
      record_id: 'edited-1',
      provider_id: 'main',
      created_at: new Date().toISOString(),
      request: { model_id: 'edit-model', prompt: '旧版单图记录', image: originalImages[0] },
      response: {
        record_id: 'edited-1',
        model_id: 'edit-model',
        images: [{ base64_data: bitmaps.result, mime_type: 'image/png' }],
      },
    };
    await page.reload();
    await page.getByRole('button', { name: '查看生成记录 旧版单图记录', exact: true }).click();
    await waitForCount(1);
    assert.equal(
      await references.nth(0).getAttribute('src'),
      `data:image/png;base64,${bitmaps.originals.png}`,
    );
    assert.equal(calls.length, 2);
    await page.getByRole('button', { name: '文字生图', exact: true }).click();
    assert.equal(await references.count(), 0);
    await page.getByRole('button', { name: '上传改图', exact: true }).click();
    assert.equal(await submit.isDisabled(), true);
    await upload.setInputFiles({
      name: '绿色叶子.png',
      mimeType: 'image/png',
      buffer: Buffer.from(bitmaps.originals.png, 'base64'),
    });
    await page.getByRole('img', { name: '参考图 1', exact: true }).waitFor();
    mode = 'hold';
    const heldRequest = new Promise((resolve) => {
      receivedCall = resolve;
    });
    await submit.click();
    await heldRequest;
    await page.getByRole('button', { name: '取消等待', exact: true }).waitFor();
    assert.equal(await upload.isDisabled(), true);
    await page.getByRole('button', { name: '取消等待', exact: true }).click();
    release();
    await page.getByRole('status').filter({ hasText: '已取消等待' }).waitFor();
    assert.equal(calls.length, 3);
    const identityRequest = new Promise((resolve) => {
      receivedCall = resolve;
    });
    await submit.click();
    await identityRequest;
    await page.getByRole('button', { name: '取消等待', exact: true }).waitFor();
    await page.evaluate(() =>
      window.dispatchEvent(new CustomEvent('evernight-access-token-change')),
    );
    release();
    await page.getByLabel('提示词', { exact: true }).waitFor();
    assert.equal(await page.getByLabel('提示词', { exact: true }).inputValue(), '');
    assert.equal(await references.count(), 0);
    assert.equal(await page.getByRole('img', { name: '生成图片 1', exact: true }).count(), 0);
    assert.equal(calls.length, 4);
    assert.deepEqual(errors, []);
    await page.close();
  }
  console.log(
    'Image editing uploads, preview, submission, history, errors, cancellation and identity reset desktop/mobile checks passed',
  );
} finally {
  await browser.close();
}
