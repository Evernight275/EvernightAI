import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const base = process.env.FRONTEND_URL || 'http://127.0.0.1:5173';
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route('**/__markdown-streaming', (route) =>
    route.fulfill({
      contentType: 'text/html',
      body: '<!doctype html><div id="app"></div>',
    }),
  );
  await page.goto(`${base}/__markdown-streaming`);
  await page.evaluate(async () => {
    const { createApp, h, nextTick, ref } = await import('/node_modules/.vite/deps/vue.js');
    const { default: MarkdownContent } = await import('/src/components/common/MarkdownContent.vue');
    const source = ref('# Stable\n\n```ts\nconst value = 1\n```\n\nTail');
    const app = createApp({ render: () => h(MarkdownContent, { source: source.value }) });
    app.mount('#app');
    await nextTick();
    const firstBlock = document.querySelector('.markdown-block');
    const frames = new Map();
    let sequence = 0;
    const requestFrame = window.requestAnimationFrame;
    const cancelFrame = window.cancelAnimationFrame;
    window.requestAnimationFrame = (callback) => {
      frames.set(++sequence, callback);
      return sequence;
    };
    window.cancelAnimationFrame = (id) => frames.delete(id);
    window.markdownStreamTest = {
      pending: () => frames.size,
      text: () => document.querySelector('.markdown-content')?.textContent,
      stable: () => document.querySelector('.markdown-block') === firstBlock,
      async append(text) {
        source.value += text;
        await nextTick();
      },
      async flush() {
        const pending = [...frames.values()];
        frames.clear();
        pending.forEach((callback) => callback(performance.now()));
        await nextTick();
      },
      unmount() {
        app.unmount();
        const pending = frames.size;
        window.requestAnimationFrame = requestFrame;
        window.cancelAnimationFrame = cancelFrame;
        return pending;
      },
    };
  });

  const initial = await page.locator('.markdown-content').textContent();
  await page.evaluate(() => window.markdownStreamTest.append(' first'));
  assert.equal(await page.evaluate(() => window.markdownStreamTest.pending()), 1);
  assert.equal(await page.locator('.markdown-content').textContent(), initial);

  await page.evaluate(async () => {
    for (let index = 0; index < 100; index++) await window.markdownStreamTest.append(' delta');
  });
  assert.equal(await page.evaluate(() => window.markdownStreamTest.pending()), 1);
  await page.evaluate(() => window.markdownStreamTest.flush());
  assert.ok(
    (await page.locator('.markdown-content').textContent()).endsWith(' delta'.repeat(100) + '\n'),
  );
  assert.equal(await page.evaluate(() => window.markdownStreamTest.stable()), true);

  await page.evaluate(() => window.markdownStreamTest.append(' next frame'));
  assert.equal(await page.evaluate(() => window.markdownStreamTest.pending()), 1);
  await page.evaluate(() => window.markdownStreamTest.flush());
  assert.ok((await page.locator('.markdown-content').textContent()).endsWith(' next frame\n'));

  await page.evaluate(() => window.markdownStreamTest.append(' removed'));
  assert.equal(await page.evaluate(() => window.markdownStreamTest.pending()), 1);
  assert.equal(await page.evaluate(() => window.markdownStreamTest.unmount()), 0);
  assert.deepEqual(errors, []);
  console.log(
    'Markdown frame updates, latest delta, stable blocks and unmount cancellation passed.',
  );
} finally {
  await browser.close();
}
