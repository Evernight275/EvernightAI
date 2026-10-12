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
        if (dimension === 'stop_reason')
          return rows([
            { dimensions: { stop_reason: null }, metrics: { run_count: 2 } },
            { dimensions: { stop_reason: 'tool_rounds_exhausted' }, metrics: { run_count: 3 } },
          ]);
        if (dimension === 'event_type')
          return rows([
            {
              dimensions: { event_type: 'tool_failed', error_type: 'ToolPolicyError' },
              metrics: { event_count: 9, distinct_run_count: 4 },
            },
            {
              dimensions: { event_type: 'run_stopped', error_type: 'RemoteProtocolError' },
              metrics: { event_count: 2, distinct_run_count: 2 },
            },
            {
              dimensions: { event_type: 'run_stopped', error_type: null },
              metrics: { event_count: 40, distinct_run_count: 40 },
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
      const traceRun = {
        run_id: 'run-1',
        request: { provider_id: 'p', model_id: 'model-a', context_id: 'c' },
        status: 'finished',
        usage: { prompt_tokens: 1200, completion_tokens: 300, total_tokens: 1500 },
        history: { started_at: '2026-10-11T16:42:00Z' },
      };
      if (path === '/agent-runs') return json([traceRun]);
      if (path === '/agent-runs/run-1') return json(traceRun);
      if (path === '/agent-runs/run-1/trace') {
        const at = (ms) => new Date(Date.UTC(2026, 9, 11, 16, 42, 0, ms)).toISOString();
        const tool = { tool_call_id: 't1', tool_call: { name: 'restricted_shell' } };
        return json([
          { sequence: 1, event_type: 'run_started', occurred_at: at(0) },
          { sequence: 2, event_type: 'chat_completed', occurred_at: at(2000) },
          { sequence: 3, event_type: 'tool_started', occurred_at: at(2000), tool_call: tool },
          {
            sequence: 4,
            event_type: 'tool_completed',
            occurred_at: at(3500),
            tool_call: tool,
            metadata: { duration_ms: 1500 },
          },
          { sequence: 5, event_type: 'chat_completed', occurred_at: at(6500) },
          { sequence: 6, event_type: 'run_stopped', occurred_at: at(6500) },
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
    assert.equal(requests.length, 7);
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
    const tools = view
      .locator('.data-chart')
      .filter({ has: page.locator('figcaption', { hasText: '工具调用' }) });
    assert.deepEqual(await tools.locator('.data-bar-label').allInnerTexts(), [
      'restricted_shell',
      'read_text_file',
    ]);
    assert.ok((await tools.innerText()).includes('失败 3 次'));
    const runFailures = view.locator('.data-chart').filter({ hasText: '运行失败原因' });
    assert.deepEqual(await runFailures.locator('.data-bar-label').allInnerTexts(), [
      '工具轮次用尽',
      'RemoteProtocolError',
    ]);
    assert.deepEqual(await runFailures.locator('.data-bar-value').allInnerTexts(), ['3', '2']);
    const toolFailures = view.locator('.data-chart').filter({ hasText: '工具失败原因' });
    assert.deepEqual(await toolFailures.locator('.data-bar-label').allInnerTexts(), [
      'ToolPolicyError',
    ]);
    assert.ok((await toolFailures.innerText()).includes('涉及 4 次运行'));
    const cost = view.locator('.data-token-cost');
    // No cache usage was reported, so input is not split into cached and uncached.
    assert.deepEqual(await cost.locator('.data-stack-legend span').allInnerTexts(), [
      '输入',
      '输出',
    ]);
    assert.equal(await cost.locator('tbody tr').count(), 2);
    const trail = view.locator('.data-run-timeline');
    await trail.locator('.tool-timeline-row').first().waitFor();
    assert.deepEqual(await trail.locator('.tool-timeline-name').allInnerTexts(), [
      '模型响应 1',
      'restricted_shell',
      '模型响应 2',
    ]);
    assert.deepEqual(await trail.locator('.tool-timeline-legend span').allInnerTexts(), [
      '工具调用',
      '模型响应',
    ]);
    assert.equal(await trail.locator('.data-run-facts dd').first().innerText(), '5.0 秒');
    await trail.locator('.tool-timeline-row').nth(1).hover();
    assert.ok((await trail.getByRole('tooltip').innerText()).includes('1.5 秒'));
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.screenshot({ path: `${screenshots}/${width}-data-dashboard.png` });
    await runs.locator('summary').click();
    await tools.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${screenshots}/${width}-data-breakdown.png` });
    await page.screenshot({ path: `${screenshots}/${width}-data-full.png`, fullPage: true });
    await trail.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${screenshots}/${width}-data-trail.png` });

    await view.getByRole('button', { name: '近 7 天', exact: true }).click();
    await page.waitForFunction(
      () => document.querySelector('.data-tile dd')?.textContent?.trim() === '16',
    );
    assert.equal(await runs.locator('.data-column').count(), 7);
    await view.getByRole('button', { name: '全部', exact: true }).click();
    await page.waitForFunction(() => document.querySelectorAll('.data-column').length === 12);
    // "All" drops the day filter; the failure queries keep their own.
    assert.ok(
      requests
        .slice(-7)
        .every((request) => request.filters.every((filter) => !filter.field_id.endsWith('_day'))),
    );

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
    assert.equal(requests.length, before + 7);

    // Switching identity clears data even while this workspace is hidden.
    if (width <= 760) await page.getByRole('button', { name: '会话管理', exact: true }).click();
    await page.getByRole('link', { name: '图像生成', exact: true }).click();
    await page.locator('.image-page').waitFor();
    assert.equal(await view.isVisible(), false);
    const beforeIdentityChange = requests.length;
    await page.evaluate(() => window.dispatchEvent(new Event('evernight-access-token-change')));
    await page.waitForFunction(() => !document.querySelector('.data-tiles'));
    assert.equal(requests.length, beforeIdentityChange);
    await page.goBack();
    await page.waitForFunction(
      () => document.querySelector('.data-tile dd')?.textContent?.trim() === '1,284',
    );
    assert.equal(requests.length, beforeIdentityChange + 7);
    assert.deepEqual(errors, []);
    console.log(
      `${width}px: data dashboard tiles, charts, ranges, failure and view switching passed`,
    );
    await page.close();
  }
} finally {
  await browser.close();
}
