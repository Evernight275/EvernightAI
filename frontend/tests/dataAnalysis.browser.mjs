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
const day = (offset) => new Date(Date.now() - offset * 86400000).toISOString().slice(0, 10);
try {
  for (const width of [1440, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    const errors = [];
    const requests = [];
    let fail = false;
    page.on('pageerror', (error) => errors.push(error.message));
    await page.addInitScript(() => {
      window.EVERNIGHTAI_API_BASE = '/mock-api';
    });
    await page.route('**/mock-api/**', async (route) => {
      const path = new URL(route.request().url()).pathname.replace('/mock-api', '');
      const json = (value) => route.fulfill({ json: value });
      if (path === '/health' || path === '/ready') return json({ status: 'ready' });
      if (path === '/data-analysis/statistics') {
        const request = route.request().postDataJSON();
        requests.push(request);
        if (fail)
          return route.fulfill({ status: 503, json: { error: { message: '统计服务暂时不可用' } } });
        const recent = request.filters?.[0]?.value >= day(6);
        const rows = (items) => json({ source_id: request.source_id, rows: items });
        const dimension = request.dimensions?.[0];
        if (dimension === 'created_day')
          return rows(
            [
              [day(5), 4, 52000],
              [day(2), 9, 131000],
              [day(0), 3, 40500],
            ].map(([created_day, run_count, total_tokens_total]) => ({
              dimensions: { created_day },
              metrics: { run_count, total_tokens_total },
            })),
          );
        if (dimension === 'model_id')
          return rows([
            {
              dimensions: { model_id: 'model-with-a-very-long-identifier-for-layout-checks' },
              metrics: { run_count: 12, total_tokens_total: 180000, successful_run_rate: 0.75 },
            },
            {
              dimensions: { model_id: null },
              metrics: { run_count: 4, total_tokens_total: 43500, successful_run_rate: 1 },
            },
          ]);
        if (dimension === 'tool_name')
          return rows([
            { dimensions: { tool_name: null }, metrics: { tool_call_count: 0 } },
            {
              dimensions: { tool_name: 'restricted_shell' },
              metrics: { tool_call_count: 21, tool_failure_count: 3 },
            },
            {
              dimensions: { tool_name: 'read_text_file' },
              metrics: { tool_call_count: 8, tool_failure_count: 0 },
            },
          ]);
        if (request.source_id === 'agent_trace_events')
          return rows([
            {
              metrics: {
                tool_call_count: 29,
                tool_failure_count: 3,
                tool_approval_required_count: 5,
              },
            },
          ]);
        return rows([
          {
            metrics: {
              run_count: recent ? 16 : 1284,
              successful_run_rate: 0.8125,
              failed_run_rate: 0.0625,
              distinct_session_count: 6,
              total_tokens_total: 223500,
              prompt_tokens_total: 200000,
              completion_tokens_total: 23500,
              cached_prompt_tokens_total: null,
              cache_observed_prompt_tokens_total: null,
            },
          },
        ]);
      }
      return json([]);
    });
    await page.goto(`${base}/chat.html`);
    if (width <= 760) await page.getByRole('button', { name: '会话管理', exact: true }).click();
    await page.getByRole('link', { name: '数据分析', exact: true }).click();
    const view = page.getByRole('region', { name: '数据分析', exact: true });
    await view.getByText('运行次数', { exact: true }).first().waitFor();
    assert.equal(new URL(page.url()).hash, '#data');
    assert.equal(await page.locator('.chat-view').isVisible(), false);
    const tile = (label) =>
      view.locator('.data-tile').filter({ has: page.getByText(label, { exact: true }) });
    assert.equal(await tile('运行次数').locator('dd').innerText(), '1,284');
    assert.equal(await tile('成功率').locator('dd').innerText(), '81%');
    assert.equal(await tile('Token 用量').locator('dd').innerText(), '224K');
    // Missing cache usage is unknown: it is neither 0% nor estimated.
    assert.equal(await tile('缓存读取占比').locator('dd').innerText(), '—');
    assert.ok((await tile('缓存读取占比').innerText()).includes('未返回缓存统计'));
    assert.equal(await tile('工具调用').locator('dd').innerText(), '29');
    assert.equal(requests.length, 5);
    assert.ok(requests.every((request) => request.filters[0].value === day(29)));

    const runs = view.locator('.data-chart').filter({ hasText: '每日运行次数' });
    assert.equal(await runs.locator('.data-column').count(), 30);
    await runs.locator('.data-column').last().hover();
    assert.ok((await runs.getByRole('tooltip').innerText()).includes('3 次'));
    await runs.locator('summary').click();
    assert.equal(await runs.locator('tbody tr').count(), 30);
    const models = view.locator('.data-chart').filter({ hasText: '按模型' });
    assert.deepEqual(await models.locator('.data-bar-value').allInnerTexts(), ['12', '4']);
    assert.ok((await models.innerText()).includes('未记录模型'));
    const tools = view.locator('.data-chart').filter({ hasText: '工具调用' });
    assert.deepEqual(await tools.locator('.data-bar-label').allInnerTexts(), [
      'restricted_shell',
      'read_text_file',
    ]);
    assert.ok((await tools.innerText()).includes('失败 3 次'));
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.screenshot({ path: `${screenshots}/${width}-data-dashboard.png` });
    await runs.locator('summary').click();
    await tools.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${screenshots}/${width}-data-breakdown.png` });

    await view.getByRole('button', { name: '近 7 天', exact: true }).click();
    await page.waitForFunction(
      () => document.querySelector('.data-tile dd')?.textContent?.trim() === '16',
    );
    assert.equal(await runs.locator('.data-column').count(), 7);
    await view.getByRole('button', { name: '全部', exact: true }).click();
    await page.waitForFunction(() => document.querySelectorAll('.data-column').length === 12);
    assert.equal(requests.at(-1).filters.length, 0);

    fail = true;
    await view.getByRole('button', { name: '刷新数据', exact: true }).click();
    await view.getByRole('alert').filter({ hasText: '统计服务暂时不可用' }).waitFor();
    assert.equal(await view.getByRole('alert').count(), 1);
    assert.equal(await tile('运行次数').locator('dd').innerText(), '—');
    fail = false;

    if (width <= 760) await page.getByRole('button', { name: '会话管理', exact: true }).click();
    const before = requests.length;
    await page.getByRole('link', { name: '图像生成', exact: true }).click();
    await page.locator('.image-page').waitFor();
    assert.equal(await view.isVisible(), false);
    await page.goBack();
    await view.waitFor();
    await page.waitForFunction(
      () => document.querySelector('.data-tile dd')?.textContent?.trim() === '1,284',
    );
    assert.equal(requests.length, before + 5);

    // Switching identity clears data even while this workspace is hidden.
    if (width <= 760) await page.getByRole('button', { name: '会话管理', exact: true }).click();
    await page.getByRole('link', { name: '图像生成', exact: true }).click();
    await page.locator('.image-page').waitFor();
    assert.equal(await view.isVisible(), false);
    const beforeIdentityChange = requests.length;
    await page.evaluate(() => window.dispatchEvent(new Event('evernight-api-key-change')));
    await page.waitForFunction(() => !document.querySelector('.data-tiles'));
    assert.equal(requests.length, beforeIdentityChange);
    await page.goBack();
    await page.waitForFunction(
      () => document.querySelector('.data-tile dd')?.textContent?.trim() === '1,284',
    );
    assert.equal(requests.length, beforeIdentityChange + 5);
    assert.deepEqual(errors, []);
    console.log(
      `${width}px: data dashboard tiles, charts, ranges, failure and view switching passed`,
    );
    await page.close();
  }
} finally {
  await browser.close();
}
