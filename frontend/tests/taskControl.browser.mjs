import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const base = process.env.FRONTEND_URL || 'http://127.0.0.1:5173';
const browser = await chromium.launch({ headless: true });
try {
  for (const width of [1440, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 1000 } });
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    const session = {
      session_id: 's',
      context_id: 'ctx',
      title: '任务控制测试',
      provider_id: 'p',
      model_id: 'm',
    };
    const runs = [];
    let starts = 0;
    let retries = 0;
    let cancels = 0;
    const tool = {
      tool_call_id: 'write',
      tool_call: { name: 'write_text_file', arguments: { path: 'note.txt', content: 'saved' } },
    };
    await page.exposeFunction('recordStart', (request) => {
      starts++;
      runs.push({
        run_id: request.metadata.run_id,
        request,
        status: 'running',
        trace: [],
        history: {
          started_at: new Date().toISOString(),
          message_offset: 0,
        },
      });
      if (request.metadata?.reply_only_of) {
        const run = runs.at(-1);
        run.response = {
          model_id: 'm',
          message: {
            role: 'assistant',
            content: [{ type: 'text', text: '根据已保存结果回复完成' }],
          },
        };
        run.status = 'finished';
        run.stop_reason = 'finished';
        run.trace = [{ event_type: 'chat_completed', response: run.response }];
        return run.trace;
      }
    });
    await page.addInitScript(() => {
      window.EVERNIGHTAI_API_BASE = '/mock-api';
      const fetcher = window.fetch;
      window.fetch = async (url, options) => {
        if (String(url).endsWith('/agent-runs/stream')) {
          const events = await window.recordStart(JSON.parse(options.body));
          if (events)
            return new Response(
              events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('') +
                'data: [DONE]\n\n',
              { headers: { 'content-type': 'text/event-stream' } },
            );
          return new Response(
            new ReadableStream({
              start(controller) {
                const encoder = new TextEncoder();
                window.emitTask = (event) =>
                  controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
                window.failTask = () => {
                  controller.enqueue(
                    encoder.encode(
                      'event: error\ndata: {"error":{"type":"ProviderResponseError","message":"上游额度不足"}}\n\n',
                    ),
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
        return fetcher(url, options);
      };
    });
    await page.route('**/mock-api/**', async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname.replace('/mock-api', '');
      const json = (value) => route.fulfill({ json: value });
      if (path === '/health' || path === '/ready') return json({ status: 'ready' });
      if (path === '/providers')
        return json([{ provider_id: 'p', name: 'Test', type: 'openai_responses' }]);
      if (path === '/providers/p/models') return json([{ model_id: 'm' }]);
      if (path === '/sessions') return json([session]);
      if (path === '/sessions/s') return json(session);
      if (path === '/contexts/ctx') return json({ context_id: 'ctx', messages: [] });
      if (path === '/agent-runs') return json(runs);
      if (path.endsWith('/cancel')) {
        cancels++;
        const run = runs.find((item) => path.includes(item.run_id));
        run.status = 'canceled';
        run.trace.push({ event_type: 'run_stopped', metadata: { reason: 'canceled' } });
        return json(run);
      }
      if (path.endsWith('/retry/stream')) {
        retries++;
        const source = runs.find((item) => path === `/agent-runs/${item.run_id}/retry/stream`);
        const body = request.postDataJSON();
        const response = {
          model_id: 'm',
          message: { role: 'assistant', content: [{ type: 'text', text: '重试完成' }] },
        };
        const trace = [{ event_type: 'chat_completed', response }];
        runs.push({
          ...source,
          run_id: body.retried_run_id,
          request: {
            ...source.request,
            metadata: {
              ...source.request.metadata,
              run_id: body.retried_run_id,
              retry_of: source.run_id,
            },
          },
          status: 'finished',
          stop_reason: 'finished',
          response,
          trace,
        });
        return route.fulfill({
          contentType: 'text/event-stream',
          body:
            trace.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('') +
            'data: [DONE]\n\n',
        });
      }
      if (path.startsWith('/agent-runs/'))
        return json(runs.find((item) => path === `/agent-runs/${item.run_id}`));
      return json([]);
    });
    await page.goto(`${base}/chat.html`);
    if (width <= 760) await page.getByRole('button', { name: '会话管理', exact: true }).click();
    await page.getByRole('button', { name: session.title, exact: true }).click();
    await page.locator('#chat-message').fill('修改文件');
    await page.getByRole('button', { name: '发送', exact: true }).click();
    await page.waitForFunction(() => !!window.emitTask);
    const first = runs.at(-1);
    first.trace.push({
      event_type: 'tool_started',
      tool_call: tool,
      occurred_at: new Date().toISOString(),
    });
    await page.evaluate((event) => window.emitTask(event), first.trace[0]);
    await page.locator('.chat-inline-tool-status').filter({ hasText: '执行中' }).waitFor();
    // Refresh reconnects to the existing run without another POST or tool execution.
    await page.reload();
    await page.locator('.chat-inline-tool-status').filter({ hasText: '执行中' }).waitFor();
    assert.equal(starts, 1);
    assert.equal(retries, 0);
    await page.getByRole('button', { name: '停止当前运行', exact: true }).click();
    await page.getByText('请求已取消', { exact: true }).waitFor();
    assert.equal(cancels, 1);
    assert.equal(starts, 1);
    await page.reload();
    await page.getByText('请求已取消', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: '停止当前运行', exact: true }).count(), 0);

    // The file result survives a later provider error, including a full page reload.
    await page.locator('#chat-message').fill('第二次修改');
    await page.getByRole('button', { name: '发送', exact: true }).click();
    await page.waitForFunction(() => !!window.emitTask);
    const failed = runs.at(-1);
    failed.trace = [
      { event_type: 'tool_started', tool_call: tool, occurred_at: new Date().toISOString() },
      {
        event_type: 'tool_completed',
        tool_call: tool,
        tool_result: {
          tool_call_id: 'write',
          tool_call_result: {
            path: 'note.txt',
            bytes_written: 5,
            diff: '--- a/note.txt\n+++ b/note.txt\n@@ -1 +1 @@\n-old\n+saved\n',
          },
        },
        metadata: { duration_ms: 1800 },
      },
      {
        event_type: 'run_stopped',
        error_type: 'ProviderResponseError',
        error_message: '上游额度不足',
      },
    ];
    failed.status = 'failed';
    await page.evaluate((trace) => {
      trace.slice(0, 2).forEach(window.emitTask);
      window.failTask();
    }, failed.trace);
    await page
      .locator('.chat-request-status .chat-status-error')
      .filter({ hasText: '上游额度不足' })
      .waitFor();
    assert.equal(await page.locator('.chat-tool-card .tool-diff').count(), 1);
    await page.reload();
    await page
      .locator('.chat-request-status .chat-status-error')
      .filter({ hasText: '上游额度不足' })
      .waitFor();
    assert.equal(await page.locator('.chat-tool-card .tool-diff').count(), 1);
    assert.equal(await page.locator('.chat-tool-card .tool-duration').last().innerText(), '1.8 秒');
    assert.equal(starts, 2);
    assert.equal(retries, 0);
    await page.getByRole('button', { name: '重试', exact: true }).click();
    await page.getByRole('group', { name: '确认重试', exact: true }).waitFor();
    assert.ok(
      (await page.getByRole('group', { name: '确认重试' }).innerText()).includes('write_text_file'),
    );
    assert.equal(retries, 0);
    await page.getByRole('button', { name: '取消重试', exact: true }).click();
    assert.equal(retries, 0);
    await page.getByRole('button', { name: '重试', exact: true }).click();
    await page.getByRole('button', { name: '仅重试回复', exact: true }).click();
    await page.getByText('根据已保存结果回复完成', { exact: true }).waitFor();
    const replyRequest = runs.at(-1).request;
    assert.deepEqual(replyRequest.tools, []);
    assert.equal(replyRequest.max_tool_rounds, 0);
    assert.ok(JSON.stringify(replyRequest.messages).includes('saved'));
    assert.equal(retries, 0);
    assert.equal(starts, 3);
    await page.reload();
    await page.getByText('根据已保存结果回复完成', { exact: true }).waitFor();
    assert.equal(await page.getByText('根据已保存的工具结果继续回复', { exact: true }).count(), 1);
    assert.equal(
      await page.locator('.chat-message--user').filter({ hasText: '此次只能回复' }).count(),
      0,
    );
    await page.goto(`${base}/chat.html?run=${failed.run_id}&session=s`);
    await page.getByRole('button', { name: '重试', exact: true }).click();
    await page.getByRole('button', { name: '确认重新执行', exact: true }).click();
    await page.getByText('重试完成', { exact: true }).waitFor();
    assert.equal(retries, 1);
    assert.equal(starts, 3);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    assert.deepEqual(errors, []);
    await page.close();
  }
  console.log(
    'Task control acceptance passed: refresh, stop, preserved results, specific errors and explicit retry.',
  );
} finally {
  await browser.close();
}
