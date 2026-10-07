import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { chromium } from 'playwright';

const base = process.env.FRONTEND_URL || 'http://127.0.0.1:5173';
const screenshots = process.env.SCREENSHOT_DIR || '/tmp/evernight-attachments';
await mkdir(screenshots, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
});
try {
  for (const width of [1440, 390, 320]) {
    const page = await browser.newPage({ viewport: { width, height: 850 } });
    const png = Buffer.from(
      await page.evaluate(() => {
        const canvas = document.createElement('canvas');
        canvas.width = canvas.height = 4;
        canvas.getContext('2d').fillRect(0, 0, 4, 4);
        return canvas.toDataURL('image/png').split(',')[1];
      }),
      'base64',
    );
    const errors = [],
      sent = [],
      uploads = new Map();
    let uploadCount = 0,
      failUpload = true,
      holdUpload = false,
      releaseUpload,
      uploadStarted,
      run;
    const session = {
      session_id: 'image-session',
      context_id: 'image-context',
      title: '图片会话',
      provider_id: 'test',
      model_id: 'vision',
    };
    const context = { context_id: 'image-context', messages: [] };
    page.on('pageerror', (error) => errors.push(error.message));
    await page.addInitScript(() => {
      window.EVERNIGHTAI_API_BASE = '/mock-api';
      localStorage.setItem('evernight.apiKey', 'image-test-key');
    });
    await page.route('**/mock-api/**', async (route) => {
      const request = route.request(),
        url = new URL(request.url()),
        path = url.pathname.replace('/mock-api', '');
      const json = (value, status = 200) => route.fulfill({ status, json: value });
      if (path === '/health' || path === '/ready') return json({ status: 'ok' });
      if (path === '/providers')
        return json([
          {
            provider_id: 'test',
            name: 'Test',
            type: 'openai',
            model: {
              vision: { model_id: 'vision', capabilities: [] },
              text: { model_id: 'text-model', capabilities: ['chat'] },
            },
          },
        ]);
      if (path === '/providers/test/models')
        return json([
          { model_id: 'vision', capabilities: [] },
          { model_id: 'text-model', capabilities: [] },
        ]);
      if (path === '/sessions') return json([session]);
      if (path === '/sessions/image-session') return json(session);
      if (path === '/contexts/image-context') return json(context);
      if (path === '/files/upload') {
        uploadCount++;
        assert.equal(request.headers()['x-evernight-api-key'], 'image-test-key');
        assert.equal(request.headers()['content-type'], 'image/png');
        const bytes = request.postDataBuffer();
        assert.ok(bytes?.subarray(0, 8).equals(png.subarray(0, 8)), 'binary upload');
        if (failUpload) {
          failUpload = false;
          return json({ error: { message: '临时上传失败' } }, 503);
        }
        const artifact = {
          artifact_id: `artifact-${uploadCount}`,
          name: url.searchParams.get('filename'),
          title: null,
          mime_type: 'image/png',
          size_bytes: bytes.length,
          preview_kind: 'image',
          created_at: '2026-10-07T00:00:00Z',
        };
        uploads.set(artifact.artifact_id, artifact);
        if (holdUpload)
          await new Promise((resolve) => {
            releaseUpload = resolve;
            uploadStarted();
          });
        return json(artifact, 201).catch(() => {});
      }
      if (path.startsWith('/files/')) {
        const artifactId = path.split('/')[2];
        if (!uploads.has(artifactId)) return json({ error: { message: '图片不存在' } }, 404);
        if (path.endsWith('/content'))
          return route.fulfill({ contentType: 'image/png', body: png });
        return json(uploads.get(artifactId));
      }
      if (path === '/agent-runs/stream') {
        const data = request.postDataJSON();
        sent.push(data);
        run = {
          run_id: data.metadata.run_id,
          request: data,
          status: 'finished',
          steps: [],
          pending_approval_requests: [],
          stop_reason: 'finished',
          response: {
            model_id: 'vision',
            message: { role: 'assistant', content: [{ type: 'text', text: '图片已收到' }] },
          },
        };
        context.messages.push(...data.messages, run.response.message);
        return route.fulfill({ contentType: 'text/event-stream', body: 'data: [DONE]\n\n' });
      }
      if (path === '/agent-runs') return json(run ? [run] : []);
      if (path.startsWith('/agent-runs/')) return json(path.endsWith('/trace') ? [] : run);
      return json([]);
    });
    async function selectSession() {
      if (width <= 760) await page.getByRole('button', { name: '会话管理', exact: true }).click();
      await page.getByRole('button', { name: '图片会话', exact: true }).click();
      await page.waitForFunction(() => !document.querySelector('#chat-message').disabled);
    }
    async function add(name = 'one.png') {
      await page
        .locator('.chat-composer input[type="file"]')
        .setInputFiles({ name, mimeType: 'image/png', buffer: png });
    }
    async function waitReady(count) {
      await page.waitForFunction((expected) => {
        const items = document.querySelectorAll('.chat-attachment');
        return (
          items.length === expected &&
          !document.querySelector('.chat-attachment [role="alert"]') &&
          !document.querySelector('.chat-attachment [role="status"]') &&
          [...items].every((item) => item.querySelector('img')?.complete)
        );
      }, count);
    }
    async function transfer(kind, name) {
      await page.evaluate(
        ({ kind, name, bytes }) => {
          const data = new DataTransfer();
          data.items.add(new File([Uint8Array.from(bytes)], name, { type: 'image/png' }));
          document
            .querySelector(kind === 'paste' ? '#chat-message' : '.chat-composer form')
            .dispatchEvent(
              kind === 'paste'
                ? new ClipboardEvent('paste', {
                    clipboardData: data,
                    bubbles: true,
                    cancelable: true,
                  })
                : new DragEvent('drop', { dataTransfer: data, bubbles: true, cancelable: true }),
            );
        },
        { kind, name, bytes: [...png] },
      );
    }
    await page.goto(`${base}/chat.html`);
    await selectSession();
    await add();
    await page.getByRole('alert').filter({ hasText: '临时上传失败' }).waitFor();
    await page
      .locator('.chat-attachment')
      .getByRole('button', { name: '重试', exact: true })
      .click();
    await waitReady(1);
    assert.equal(uploadCount, 2);
    await page.locator('#chat-message').fill('上传以后修改文字');
    await transfer('paste', 'paste.png');
    await waitReady(2);
    await transfer('drop', 'drop.png');
    await waitReady(3);
    await page.getByRole('button', { name: '移除 paste.png', exact: true }).click();
    await waitReady(2);
    const draft = await page.evaluate(() =>
      sessionStorage.getItem('evernight.chatDraft.image-session'),
    );
    assert.ok(draft?.includes('artifact-2'));
    assert.ok(!draft?.includes('base64') && !draft?.includes('blob:'), 'metadata-only draft');
    await page.reload();
    await selectSession();
    await waitReady(2);
    assert.equal(await page.locator('#chat-message').inputValue(), '上传以后修改文字');
    await page.getByRole('button', { name: '预览 one.png', exact: true }).click();
    await page.getByRole('dialog', { name: '图片预览：one.png', exact: true }).waitFor();
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('dialog.chat-image-preview-dialog[open]').count(), 0);
    await page.getByRole('button', { name: '选择模型', exact: true }).click();
    await page.getByRole('button', { name: 'text-model', exact: true }).click();
    await page.getByRole('status').filter({ hasText: '所选模型已声明不支持图像识别' }).waitFor();
    assert.ok(await page.getByRole('button', { name: '发送', exact: true }).isDisabled());
    await page.getByRole('button', { name: '选择模型', exact: true }).click();
    await page.getByRole('button', { name: 'vision', exact: true }).click();
    await page.locator('#chat-message').fill('');
    await page.screenshot({ path: `${screenshots}/${width}-draft.png` });
    await page.getByRole('button', { name: '发送', exact: true }).click();
    await page.getByText('图片已收到', { exact: true }).waitFor();
    assert.equal(sent.length, 1);
    assert.equal(sent[0].messages[0].content.filter((part) => part.type === 'image').length, 2);
    assert.ok(!JSON.stringify(sent[0]).includes('data:'), 'reference-only model request');
    assert.equal(await page.locator('.chat-attachment').count(), 0);
    await page.reload();
    await selectSession();
    await page.locator('.chat-message-image').first().waitFor();
    assert.equal(
      await page.locator('.chat-attachment').count(),
      0,
      'sent files do not reappear in draft',
    );
    assert.ok(await page.locator('body').evaluate((element) => element.scrollWidth <= innerWidth));
    await page.screenshot({ path: `${screenshots}/${width}-history.png` });
    await page.locator('.chat-message-image-button').first().click();
    await page.getByRole('button', { name: '关闭图片预览', exact: true }).click();
    if (width === 1440) {
      const originalImages = structuredClone(sent[0].messages[0].content);
      originalImages[1].detail = 'high';
      originalImages[1].metadata.preserve = 'image metadata';
      const originalText = {
        type: 'text',
        text: '原输入',
        metadata: { preserve: 'text metadata' },
      };
      run = {
        ...run,
        status: 'canceled',
        response: null,
        request: {
          ...run.request,
          messages: [
            {
              role: 'user',
              metadata: { preserve: 'message metadata' },
              content: [originalImages[0], originalText, originalImages[1]],
            },
          ],
        },
      };
      await page.goto(`${base}/chat.html?run=${run.run_id}&edit=1`);
      await page.getByText('原请求已载入草稿', { exact: true }).waitFor();
      await waitReady(2);
      await page.getByRole('button', { name: '移除 one.png', exact: true }).click();
      await page.locator('#chat-message').fill('编辑后的消息');
      await page.getByRole('button', { name: '发送', exact: true }).click();
      await page.waitForFunction(
        () => document.querySelector('.chat-header-status').textContent === '准备就绪',
      );
      assert.equal(sent.length, 2);
      assert.deepEqual(
        sent[1].messages[0],
        {
          role: 'user',
          metadata: { preserve: 'message metadata' },
          content: [{ ...originalText, text: '编辑后的消息' }, originalImages[1]],
        },
        'editing preserves part order and metadata and removes the selected image',
      );
      const before = uploadCount;
      await page.evaluate(() => {
        const data = new DataTransfer();
        data.items.add(
          new File([new Uint8Array(20 * 1024 * 1024 + 1)], 'large.png', { type: 'image/png' }),
        );
        document
          .querySelector('.chat-composer form')
          .dispatchEvent(new DragEvent('drop', { dataTransfer: data, bubbles: true }));
      });
      await page.getByRole('alert').filter({ hasText: '单张图片不能超过 20 MiB' }).waitFor();
      assert.equal(uploadCount, before);
      await page.locator('.chat-composer input[type="file"]').setInputFiles(
        Array.from({ length: 11 }, (_, i) => ({
          name: `${i}.png`,
          mimeType: 'image/png',
          buffer: png,
        })),
      );
      await waitReady(10);
      await page.getByRole('alert').filter({ hasText: '最多添加 10 张图片' }).waitFor();
      assert.equal(uploadCount - before, 10);
      while (await page.locator('.chat-attachment-remove').count())
        await page.locator('.chat-attachment-remove').first().click();
      holdUpload = true;
      const started = new Promise((resolve) => {
        uploadStarted = resolve;
      });
      await add('late.png');
      await started;
      await page.evaluate(() => window.dispatchEvent(new CustomEvent('evernight-api-key-change')));
      releaseUpload();
      await page.waitForFunction(() => !document.querySelector('.chat-attachment'));
      assert.ok(
        await page.evaluate(
          () =>
            !Object.keys(sessionStorage)
              .filter((key) => key.startsWith('evernight.chatDraft.'))
              .some((key) => sessionStorage.getItem(key).includes('artifact-')),
        ),
      );
    }
    assert.deepEqual(errors, []);
    await page.close();
    console.log(
      `${width}px: uploads/retry, paste/drop/remove, draft/history, image-only send and capabilities passed`,
    );
  }
} finally {
  await browser.close();
}
