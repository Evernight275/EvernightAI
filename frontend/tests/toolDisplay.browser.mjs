import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { chromium } from 'playwright';

const base = process.env.FRONTEND_URL || 'http://127.0.0.1:5173';
await mkdir('/tmp/evernight-tool-display', { recursive: true });
const browser = await chromium.launch({ headless: true });
const content = (role, text) => ({ role, content: [{ type: 'text', text }] });
try {
  for (const width of [1440, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 1000 } });
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    const session = {
      session_id: 's',
      context_id: 'ctx',
      title: '工具展示测试',
      provider_id: 'p',
      model_id: 'm',
    };
    const context = { context_id: 'ctx', messages: [], metadata: {} };
    let run;
    await page.addInitScript(() => {
      window.EVERNIGHTAI_API_BASE = '/mock-api';
      Object.defineProperty(navigator, 'clipboard', {
        value: {
          writeText: async (text) => {
            window.copiedOutput = text;
          },
        },
      });
    });
    await page.route('**/mock-api/**', async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname.replace('/mock-api', '');
      const json = (value) => route.fulfill({ json: value });
      if (path === '/health' || path === '/ready') return json({ status: 'ready' });
      if (path === '/providers') return json([{ provider_id: 'p', name: 'Test', type: 'openai' }]);
      if (path === '/providers/p/models') return json([{ model_id: 'm' }]);
      if (path === '/sessions') return json([session]);
      if (path === '/sessions/s') return json(session);
      if (path === '/contexts/ctx') return json(context);
      if (path === '/agent-runs') return json(run ? [run] : []);
      if (path === '/agent-runs/stream') {
        const body = request.postDataJSON();
        const calls = [
          {
            tool_call_id: 'write',
            tool_call: {
              name: 'write_text_file',
              arguments: { path: 'src/demo.py', content: 'new' },
            },
          },
          {
            tool_call_id: 'shell',
            tool_call: {
              name: 'restricted_shell',
              arguments: { command: ['python', 'src/demo.py'] },
            },
          },
        ];
        const results = [
          {
            path: 'src/demo.py',
            bytes_written: 3,
            overwritten: true,
            diff: `--- a/src/demo.py\n+++ b/src/demo.py\n@@ -1 +1 @@\n-old\n+${'long '.repeat(120)}\n`,
            diff_truncated: false,
          },
          {
            command: ['python', 'src/demo.py'],
            returncode: 1,
            stdout: 'first\n\n' + 'long '.repeat(120) + '\n',
            stderr: '\x1b[31m<script>window.unexpectedToolScript = true</script>\x1b[0m\n',
            truncated: true,
          },
        ];
        const assistant = { ...content('assistant', '修改文件并检查结果。'), tool_calls: calls };
        const response = { model_id: 'm', message: assistant };
        const final = { model_id: 'm', message: content('assistant', '工具调用结束。') };
        const trace = [
          { sequence: 1, event_type: 'chat_completed', response },
          ...calls.flatMap((tool, index) => [
            { sequence: index * 2 + 2, event_type: 'tool_started', tool_call: tool },
            {
              sequence: index * 2 + 3,
              event_type: 'tool_completed',
              tool_call: tool,
              tool_result: { tool_call_id: tool.tool_call_id, tool_call_result: results[index] },
              metadata: { duration_ms: 2500 },
            },
          ]),
          { sequence: 6, event_type: 'chat_completed', response: final },
        ];
        context.messages.push(
          ...body.messages,
          assistant,
          ...calls.map((tool, index) => ({
            ...content('tool', JSON.stringify(results[index])),
            tool_call_id: tool.tool_call_id,
            name: tool.tool_call.name,
          })),
          final.message,
        );
        run = {
          run_id: body.metadata.run_id,
          request: body,
          status: 'finished',
          stop_reason: 'finished',
          response: final,
          trace,
          pending_approval_requests: [],
          metadata: {
            agent_runtime: {
              history_started_at: '2026-10-05T08:00:00Z',
              context_message_offset: 0,
              context_message_indices: [0, 1, 2, 3, 4],
            },
          },
        };
        return route.fulfill({
          contentType: 'text/event-stream',
          body:
            trace.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('') +
            'data: [DONE]\n\n',
        });
      }
      if (path.startsWith('/agent-runs/')) return json(run);
      return json([]);
    });
    await page.goto(`${base}/chat.html`);
    if (width <= 760) await page.getByRole('button', { name: '会话管理', exact: true }).click();
    await page.getByRole('button', { name: '工具展示测试', exact: true }).click();
    await page.locator('#chat-message').fill('修改文件并执行检查');
    await page.getByRole('button', { name: '发送', exact: true }).click();
    async function checkDisplays() {
      await page.getByText('工具调用结束。', { exact: true }).waitFor();
      const cards = page.locator('.chat-tool-card');
      assert.equal(await cards.count(), 2);
      assert.equal(await cards.locator('.tool-diff').count(), 1);
      assert.equal(await cards.locator('.tool-terminal').count(), 1);
      assert.equal(await cards.locator('.tool-duration').first().innerText(), '2.5 秒');
      assert.equal(await cards.locator('.tool-diff-line--removed code').innerText(), '-old');
      assert.equal(
        await cards.locator('.tool-diff-line--removed .tool-diff-number').first().innerText(),
        '1',
      );
      assert.ok((await cards.locator('.tool-diff-line--added').innerText()).includes('+long'));
      assert.equal(await cards.locator('.tool-terminal-exit.is-error').innerText(), '退出码 1');
      assert.equal(
        await cards.locator('.tool-terminal-command').innerText(),
        '$ python src/demo.py',
      );
      assert.ok((await cards.locator('.tool-terminal-stderr').innerText()).includes('<script>'));
      assert.equal(await cards.locator('.tool-terminal-stderr script').count(), 0);
      assert.equal(await page.evaluate(() => window.unexpectedToolScript), undefined);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      assert.ok(
        await cards.locator('.tool-diff-scroll').evaluate((el) => el.scrollWidth > el.clientWidth),
      );
      assert.ok(
        await cards
          .locator('.tool-terminal-scroll')
          .evaluate((el) => el.scrollWidth > el.clientWidth),
      );
    }
    await checkDisplays();
    await page.reload();
    await checkDisplays();
    const terminal = page.locator('.chat-tool-card .tool-terminal');
    await terminal.getByRole('button', { name: '复制', exact: true }).click();
    assert.ok((await page.evaluate(() => window.copiedOutput)).includes('$ python src/demo.py'));
    const search = terminal.getByRole('searchbox');
    await search.fill('<script>');
    assert.equal(await terminal.locator('mark').count(), 1);
    assert.equal(await terminal.locator('mark script').count(), 0);
    assert.equal(await terminal.locator('mark.is-current').innerText(), '<script>');
    await search.fill('long');
    assert.equal(await terminal.locator('mark').count(), 120);
    await terminal.getByRole('button', { name: '下一个匹配', exact: true }).click();
    assert.equal(await terminal.getByRole('status').filter({ hasText: '2/120' }).count(), 1);
    await search.fill('not present');
    assert.equal(await terminal.locator('mark').count(), 0);
    assert.ok(await terminal.getByRole('button', { name: '下一个匹配', exact: true }).isDisabled());
    await search.fill('');
    await terminal.getByRole('button', { name: '折叠输出', exact: true }).click();
    assert.equal(await terminal.locator('.tool-terminal-scroll').isVisible(), false);
    await terminal.getByRole('button', { name: '展开输出', exact: true }).click();
    assert.equal(await terminal.locator('.tool-terminal-scroll').isVisible(), true);
    const diff = page.locator('.chat-tool-card .tool-diff');
    await diff.getByRole('searchbox').fill('old');
    assert.equal(await diff.locator('mark').count(), 1);
    await diff.getByRole('searchbox').fill('');
    await page.locator('.chat-tool-card').first().locator('.chat-inline-tool > summary').click();
    assert.ok(
      await page
        .locator('.chat-tool-card')
        .first()
        .getByLabel('write_text_file 调用结果', { exact: true })
        .isVisible(),
    );
    await page.locator('.chat-tool-card').first().locator('.chat-inline-tool > summary').click();
    await page.locator('.chat-tool-card .tool-terminal').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `/tmp/evernight-tool-display/${width}.png` });
    await page.getByRole('button', { name: '运行详情', exact: true }).click();
    assert.equal(await page.locator('.chat-tool-activity .tool-display').count(), 2);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    assert.deepEqual(errors, []);
    await page.close();
  }
  console.log(
    'Tool diff and terminal browser checks passed: streaming, refresh, diagnostics, desktop and mobile.',
  );
} finally {
  await browser.close();
}
