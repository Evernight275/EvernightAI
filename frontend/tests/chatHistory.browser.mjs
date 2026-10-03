import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { chromium } from 'playwright';

const base = process.env.FRONTEND_URL || 'http://127.0.0.1:5173';
const screenshots = process.env.SCREENSHOT_DIR || '/tmp/evernight-history';
await mkdir(screenshots, { recursive: true });
const browser = await chromium.launch({ headless: true });
const content = (role, text) => ({ role, content: [{ type: 'text', text }] });
try {
  for (const width of [1440, 390]) {
    for (const status of ['canceled', 'failed']) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      const errors = [];
      const posted = [];
      page.on('pageerror', (error) => errors.push(error.message));
      const sessions = ['one', 'two'].map((id) => ({
        session_id: id,
        context_id: `ctx-${id}`,
        title: `会话 ${id}`,
        provider_id: 'p',
        model_id: 'm',
      }));
      let context = {
        context_id: 'ctx-one',
        metadata: {},
        messages: [content('user', 'saved question'), content('assistant', 'saved answer')],
      };
      const call = {
        tool_call_id: 'write',
        tool_call: { name: 'write_text_file', arguments: { path: 'notes.txt' } },
      };
      const partial = {
        model_id: 'm',
        message: { ...content('assistant', 'partial answer'), tool_calls: [call] },
      };
      const runs = {
        interrupted: {
          run_id: 'interrupted',
          status,
          request: {
            provider_id: 'p',
            model_id: 'm',
            context_id: 'ctx-one',
            messages: [content('user', 'interrupted question')],
            metadata: { session_id: 'one' },
          },
          pending_approval_requests: [],
          metadata: {
            agent_runtime: {
              history_started_at: '2026-10-03T08:00:00Z',
              ...(status === 'canceled'
                ? { context_message_offset: 2, context_message_indices: [] }
                : {}),
            },
          },
          trace: [
            { sequence: 1, event_type: 'chat_completed', response: partial },
            ...(status === 'canceled'
              ? [
                  { sequence: 2, event_type: 'tool_approval_requested', tool_call: call },
                  { sequence: 3, event_type: 'run_stopped', metadata: { reason: 'canceled' } },
                ]
              : [
                  { sequence: 2, event_type: 'tool_started', tool_call: call },
                  {
                    sequence: 3,
                    event_type: 'tool_failed',
                    tool_call: call,
                    error_type: 'PermissionError',
                    error_message: 'notes.txt: permission denied',
                  },
                  {
                    sequence: 4,
                    event_type: 'run_stopped',
                    error_type: 'ProviderError',
                    error_message: 'provider offline',
                  },
                ]),
          ],
        },
      };
      function finishRun(request, responseId, text) {
        const response = {
          response_id: responseId,
          model_id: 'm',
          message: content('assistant', text),
        };
        const offset = context.messages.length;
        runs[request.metadata.run_id] = {
          run_id: request.metadata.run_id,
          request,
          status: 'finished',
          stop_reason: 'finished',
          response,
          pending_approval_requests: [],
          metadata: {
            agent_runtime: {
              history_started_at:
                responseId === 'retried' ? '2026-10-03T08:00:30Z' : '2026-10-03T08:01:00Z',
              context_message_offset: offset,
              context_message_indices: [offset, offset + 1],
              context_history_generation: context.metadata.chat_history_generation ?? null,
            },
          },
          trace: [{ event_type: 'chat_completed', response }],
        };
        context.messages = [...context.messages, ...request.messages, response.message];
      }
      await page.addInitScript(() => {
        window.EVERNIGHTAI_API_BASE = '/mock-api';
      });
      await page.route('**/mock-api/**', async (route) => {
        const path = new URL(route.request().url()).pathname.replace('/mock-api', '');
        const json = (value) => route.fulfill({ json: value });
        if (path === '/health' || path === '/ready') return json({ status: 'ready' });
        if (path === '/providers')
          return json([{ provider_id: 'p', name: 'Test', type: 'openai' }]);
        if (path === '/providers/p/models') return json([{ model_id: 'm' }]);
        if (path === '/sessions') return json(sessions);
        if (path.startsWith('/sessions/'))
          return json(sessions.find((s) => s.session_id === path.split('/')[2]));
        if (path === '/contexts/ctx-one' && route.request().method() === 'PUT') {
          context = route.request().postDataJSON();
          return json(context);
        }
        if (path.startsWith('/contexts/'))
          return json(path.endsWith('one') ? context : { context_id: 'ctx-two', messages: [] });
        if (path === '/agent-runs/stream') {
          const request = route.request().postDataJSON();
          posted.push(request);
          finishRun(request, 'continued', 'continued answer');
          return route.fulfill({ contentType: 'text/event-stream', body: 'data: [DONE]\n\n' });
        }
        if (path === '/agent-runs/interrupted/retry/stream') {
          const { retried_run_id } = route.request().postDataJSON();
          const source = runs.interrupted.request;
          finishRun(
            {
              ...source,
              metadata: { ...source.metadata, run_id: retried_run_id, retry_of: 'interrupted' },
            },
            'retried',
            'retried answer',
          );
          return route.fulfill({ contentType: 'text/event-stream', body: 'data: [DONE]\n\n' });
        }
        if (path === '/agent-runs') return json(Object.values(runs));
        if (path.startsWith('/agent-runs/')) return json(runs[path.split('/')[2]]);
        return json([]);
      });
      async function selectSession(id) {
        if (width <= 760 && !(await page.locator('.chat-sidebar-dialog').evaluate((el) => el.open)))
          await page.getByRole('button', { name: '会话管理', exact: true }).click();
        await page.getByRole('button', { name: `会话 ${id}`, exact: true }).click();
        await page.waitForFunction(
          (title) => document.querySelector('.chat-header-title').textContent === title,
          `会话 ${id}`,
        );
        await page.waitForFunction(() => !document.querySelector('#chat-message').disabled);
      }
      async function restored() {
        await page.getByText('interrupted question', { exact: true }).waitFor();
        await page.getByText('partial answer', { exact: true }).waitFor();
        await page
          .locator('.chat-inline-tool-status')
          .filter({ hasText: status === 'canceled' ? '已取消' : '失败' })
          .waitFor();
        await page
          .locator('.chat-run-notice')
          .filter({ hasText: status === 'canceled' ? '请求已取消' : 'provider offline' })
          .waitFor();
        assert.equal(await page.getByText('interrupted question', { exact: true }).count(), 1);
        assert.equal(await page.locator('.chat-tool-card').count(), 1);
        assert.equal(await page.getByRole('button', { name: '批准', exact: true }).count(), 0);
      }
      await page.goto(`${base}/chat.html?run=interrupted`);
      await restored();
      await page.reload();
      await restored();
      await selectSession('two');
      await page.reload();
      await page.waitForFunction(
        () => document.querySelector('.chat-header-title').textContent === '会话 two',
      );
      await selectSession('one');
      await restored();
      if (status === 'failed') {
        await page.getByRole('button', { name: '重试', exact: true }).click();
        await page.getByText('retried answer', { exact: true }).waitFor();
        await restored();
        await page.reload();
        await page.getByText('retried answer', { exact: true }).waitFor();
        await restored();
        assert.equal(await page.getByText('retried answer', { exact: true }).count(), 1);
        await page.goto(`${base}/chat.html?run=interrupted`);
        await restored();
        assert.equal(await page.getByText('retried answer', { exact: true }).count(), 1);
      }
      await page.locator('#chat-message').fill('continue question');
      await page.getByRole('button', { name: '发送', exact: true }).click();
      await page.getByText('continued answer', { exact: true }).waitFor();
      await restored();
      assert.deepEqual(posted[0].messages, [content('user', 'continue question')]);
      await page.reload();
      await page.getByText('continued answer', { exact: true }).waitFor();
      await restored();
      assert.equal(await page.getByText('continued answer', { exact: true }).count(), 1);
      assert.equal(await page.getByText('continue question', { exact: true }).count(), 1);
      await selectSession('two');
      await selectSession('one');
      await restored();
      assert.equal(await page.getByText('continued answer', { exact: true }).count(), 1);
      const bounds = await page.evaluate(() => ({
        width: document.documentElement.scrollWidth,
        height: document.documentElement.scrollHeight,
      }));
      assert.ok(bounds.width <= width);
      assert.ok(bounds.height <= 901);
      await page.screenshot({ path: `${screenshots}/${width}-${status}.png` });
      await page.getByRole('button', { name: '运行详情', exact: true }).click();
      await page.getByRole('button', { name: '清空对话记录', exact: true }).click();
      await page.waitForFunction(
        () => document.querySelector('.chat-header-status').textContent === '准备就绪',
      );
      await page.getByRole('button', { name: '关闭运行详情' }).click();
      await page.reload();
      await page.waitForFunction(
        () => document.querySelector('.chat-header-title').textContent === '会话 one',
      );
      assert.equal(
        await page.locator('.chat-message, .chat-tool-card, .chat-run-notice').count(),
        0,
      );
      await page.goto(`${base}/chat.html?run=interrupted`);
      await page.waitForFunction(
        () => document.querySelector('.chat-header-title').textContent === '会话 one',
      );
      assert.equal(
        await page.locator('.chat-message, .chat-tool-card, .chat-run-notice').count(),
        0,
      );
      assert.deepEqual(errors, []);
      await page.close();
      console.log(
        `${width}px ${status}: refresh, session switching, continued chat, deduplication and clearing passed`,
      );
    }
  }
} finally {
  await browser.close();
}
