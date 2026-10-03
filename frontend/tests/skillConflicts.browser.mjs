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
const session = {
  session_id: 'session',
  context_id: 'ctx',
  provider_id: 'main',
  model_id: 'model',
  title: '技能测试',
};
function fixture() {
  return {
    run_id: 'old',
    status: 'paused',
    skill_revisions: { style: 'v1', extra: 'v1' },
    request: {
      provider_id: 'main',
      model_id: 'model',
      context_id: 'ctx',
      working_directory: 'C:/work',
      messages: [
        { role: 'user', content: [{ type: 'text', text: '原输入' }], metadata: { source: 'keep' } },
        { role: 'user', content: [{ type: 'text', text: '第二条输入' }] },
      ],
      skills: [
        { skill_name: 'style', variables: { tone: 'calm' }, metadata: { keep: true } },
        { skill_name: 'extra', variables: { count: 3 } },
      ],
      tools: [{ name: 'write_file', description: 'Write' }],
      max_tool_rounds: 3,
      recover_tool_errors: false,
      write_memory: false,
      metadata: { run_id: 'old', session_id: 'session', retry_of: 'previous', custom: 'keep' },
      tool_approvals: [],
    },
    pending_approval_requests: [1, 2].map((index) => ({
      approval_id: `approval-${index}`,
      tool_call_id: `call-${index}`,
      tool_name: `write_${index}`,
      safety_level: 'sensitive',
      tool_call: { name: `write_${index}`, arguments: { path: `file-${index}.txt` } },
    })),
    trace: [
      {
        sequence: 1,
        event_type: 'tool_completed',
        tool_call: { tool_call_id: 'completed', tool_call: { name: 'read_file' } },
        tool_result: { tool_call_id: 'completed', result: { read: true } },
      },
    ],
  };
}
try {
  for (const width of [1440, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    const errors = [];
    const calls = [];
    let run = fixture();
    let skills = ['style', 'extra'].map((name) => ({
      name,
      description: name,
      capabilities: ['agent'],
      revision: 'v1',
      is_enabled: true,
      input_schema: { type: 'object' },
    }));
    let cancelFails = true;
    let newRun = null;
    let conflictOnResume = false;
    page.on('pageerror', (error) => errors.push(error.message));
    await page.addInitScript(() => {
      window.EVERNIGHTAI_API_BASE = '/mock-api';
    });
    await page.route('**/mock-api/**', async (route) => {
      const path = new URL(route.request().url()).pathname.replace('/mock-api', '');
      const method = route.request().method();
      const data = method === 'GET' ? null : route.request().postDataJSON();
      calls.push({ path, method, data });
      const json = (value) => route.fulfill({ json: value });
      if (path === '/health' || path === '/ready') return json({ status: 'ready' });
      if (path === '/providers')
        return json([
          {
            provider_id: 'main',
            name: 'Main',
            type: 'openai',
            model: { model: { model_id: 'model' } },
          },
        ]);
      if (path.endsWith('/models')) return json([{ model_id: 'model' }]);
      if (path === '/skills') return json(skills);
      if (path === '/tools')
        return json([
          { name: 'write_file', description: 'Write' },
          { name: 'read_file', description: 'Read' },
        ]);
      if (path === '/sessions') return json([session]);
      if (path === '/sessions/session') return json(session);
      if (path === '/contexts/ctx') return json({ context_id: 'ctx', messages: [] });
      if (path === '/agent-runs') return json([run]);
      if (path === '/agent-runs/old') return json(run);
      if (path === '/agent-runs/old/cancel') {
        if (cancelFails)
          return route.fulfill({ status: 503, json: { error: { message: '取消暂时失败' } } });
        run = { ...run, status: 'canceled', pending_approval_requests: [] };
        return json(run);
      }
      if (path === '/agent-runs/old/resume/stream' && conflictOnResume) {
        skills[0].revision = 'v2';
        return route.fulfill({
          contentType: 'text/event-stream',
          body: `event: error\ndata: ${JSON.stringify({ error: { type: 'SkillConflictError', message: 'Skill changed', detail: JSON.stringify({ reason: 'revision_changed', skill_names: ['style'] }) } })}\n\n`,
        });
      }
      if (path === '/agent-runs/stream') {
        newRun = {
          ...fixture(),
          run_id: data.metadata.run_id,
          request: data,
          skill_revisions: { style: 'v2', extra: 'v1' },
          trace: [],
          pending_approval_requests: [
            {
              approval_id: 'fresh-approval',
              tool_call_id: 'fresh-call',
              tool_name: 'write_file',
              safety_level: 'sensitive',
            },
          ],
        };
        return route.fulfill({ contentType: 'text/event-stream', body: 'data: [DONE]\n\n' });
      }
      if (newRun && path === `/agent-runs/${newRun.run_id}`) return json(newRun);
      if (path.endsWith('/trace')) return json(run.trace);
      return json([]);
    });

    await page.goto(base);
    await page.getByRole('button', { name: '运行管理', exact: true }).click();
    await page.getByRole('button', { name: '管理运行', exact: true }).click();
    const decisions = page.getByLabel('审批决定');
    await decisions.nth(0).selectOption('approved');
    await page.getByRole('button', { name: '刷新详情', exact: true }).click();
    assert.equal(await decisions.nth(0).inputValue(), 'approved');
    await page.reload();
    await page.getByRole('button', { name: '运行管理', exact: true }).click();
    await page.getByRole('button', { name: '管理运行', exact: true }).click();
    assert.equal(await decisions.nth(0).inputValue(), 'approved');
    skills[0].revision = 'v2';
    await page.getByRole('button', { name: '刷新详情', exact: true }).click();
    await page.getByText('style：版本已变更', { exact: true }).waitFor();
    assert.ok(await page.getByRole('button', { name: '继续运行', exact: true }).isDisabled());
    assert.ok(await page.getByRole('button', { name: '重试运行', exact: true }).isDisabled());
    await page.screenshot({ path: `${screenshots}/${width}-settings-skill-conflict.png` });
    await page.getByRole('button', { name: '取消运行并编辑', exact: true }).click();
    await page.getByRole('dialog', { name: '确认编辑原请求' }).waitFor();
    await page.getByText('已完成：read_file', { exact: true }).waitFor();
    await page.getByRole('button', { name: '确认取消并编辑', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: '取消暂时失败' }).waitFor();
    assert.equal(await decisions.nth(0).inputValue(), 'approved');
    assert.ok(!page.url().includes('chat.html'));
    cancelFails = false;
    await page.getByRole('button', { name: '取消运行并编辑', exact: true }).click();
    await page.getByRole('button', { name: '确认取消并编辑', exact: true }).click();
    await page.waitForURL('**/chat.html?run=old*');
    await page.getByText('原请求已载入草稿', { exact: true }).waitFor();
    assert.deepEqual(
      JSON.parse(await page.locator('#chat-message').inputValue()),
      fixture().request.messages,
    );
    assert.equal(calls.filter((call) => call.path === '/agent-runs/stream').length, 0);
    await page.getByText('技能与上下文', { exact: true }).click();
    assert.deepEqual(
      JSON.parse(await page.getByLabel('本轮技能（JSON）').inputValue()),
      fixture().request.skills,
    );
    const options = page.getByLabel('运行参数（JSON）');
    const params = JSON.parse(await options.inputValue());
    assert.equal(params.max_tool_rounds, 3);
    assert.deepEqual(params.metadata, { custom: 'keep' });
    await options.fill('{invalid');
    const edited = fixture().request.messages;
    edited[0].content[0].text = '修改后的输入';
    await page.locator('#chat-message').fill(JSON.stringify(edited));
    await page.reload();
    await page.getByText('技能与上下文', { exact: true }).click();
    assert.equal(await options.inputValue(), '{invalid');
    assert.deepEqual(JSON.parse(await page.locator('#chat-message').inputValue()), edited);
    assert.equal(calls.filter((call) => call.path === '/agent-runs/stream').length, 0);
    await options.fill(JSON.stringify(params));
    await page.getByText('技能与上下文', { exact: true }).click();
    await page.screenshot({ path: `${screenshots}/${width}-edited-skill-draft.png` });
    await page.getByRole('button', { name: '发送', exact: true }).click();
    await page.locator('.chat-transcript .chat-tool-approval').waitFor();
    const sent = calls.find((call) => call.path === '/agent-runs/stream').data;
    assert.notEqual(sent.metadata.run_id, 'old');
    assert.equal(sent.working_directory, 'C:/work');
    assert.deepEqual(sent.messages, edited);
    assert.deepEqual(sent.skills, fixture().request.skills);
    assert.deepEqual(sent.tools, fixture().request.tools);
    assert.equal(sent.recover_tool_errors, false);
    assert.equal(sent.max_tool_rounds, 3);
    assert.deepEqual(sent.tool_approvals, []);
    assert.equal(sent.metadata.retry_of, undefined);
    assert.equal(sent.pause_on_approval, true);

    // Resume can conflict after the catalog was fetched, including an SSE 200 response.
    run = fixture();
    run.request.messages = [run.request.messages[0]];
    run.request.skills = [run.request.skills[0]];
    run.skill_revisions = { style: 'v1' };
    skills[0].revision = 'v1';
    conflictOnResume = true;
    cancelFails = true;
    await page.goto(`${base}/chat.html?run=old`);
    await page.locator('.chat-transcript .chat-tool-approval').first().waitFor();
    assert.equal(await page.locator('.chat-transcript .chat-tool-approval').count(), 2);
    await page
      .locator('.chat-transcript .chat-approval-actions')
      .getByRole('button', { name: '批准', exact: true })
      .nth(0)
      .click();
    await page.reload();
    await page.locator('.chat-transcript').getByText('已批准', { exact: true }).waitFor();
    assert.equal(calls.filter((call) => call.path.endsWith('/resume/stream')).length, 0);
    await page
      .locator('.chat-transcript .chat-approval-actions')
      .getByRole('button', { name: '批准', exact: true })
      .nth(1)
      .click();
    await page.getByText('style：版本已变更', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: '重试', exact: true }).count(), 0);
    assert.equal(calls.filter((call) => call.path.endsWith('/resume/stream')).length, 1);
    assert.equal(
      await page.locator('.chat-transcript').getByText('已批准', { exact: true }).count(),
      2,
    );
    await page.getByRole('button', { name: '取消运行并编辑', exact: true }).click();
    await page.getByRole('button', { name: '确认取消并编辑', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: '取消暂时失败' }).waitFor();
    assert.equal(
      await page.locator('.chat-transcript').getByText('已批准', { exact: true }).count(),
      2,
    );
    await page.screenshot({ path: `${screenshots}/${width}-chat-skill-conflict.png` });
    await page.reload();
    await page.getByText('style：版本已变更', { exact: true }).waitFor();
    assert.equal(
      await page.locator('.chat-transcript').getByText('已批准', { exact: true }).count(),
      2,
    );
    for (const [kind, text] of [
      ['disabled', '已停用'],
      ['deleted', '已删除'],
      ['legacy', '原运行未记录版本'],
    ]) {
      skills = [
        {
          name: 'style',
          description: 'Style',
          capabilities: ['agent'],
          revision: 'v1',
          is_enabled: kind !== 'disabled',
        },
      ];
      if (kind === 'deleted') skills = [];
      run.skill_revisions = kind === 'legacy' ? null : { style: 'v1' };
      await page.reload();
      await page.getByText(`style：${text}`, { exact: true }).waitFor();
    }
    run = fixture();
    run.request.messages = [run.request.messages[0]];
    run.request.skills = [run.request.skills[0]];
    run.skill_revisions = { style: 'v1' };
    skills = [
      {
        name: 'style',
        description: 'Style',
        capabilities: ['agent'],
        revision: 'v2',
        input_schema: { type: 'object' },
      },
    ];
    cancelFails = false;
    await page.reload();
    await page.getByRole('button', { name: '取消运行并编辑', exact: true }).click();
    await page.getByRole('button', { name: '确认取消并编辑', exact: true }).click();
    await page.getByText('原请求已载入草稿', { exact: true }).waitFor();
    assert.equal(await page.locator('#chat-message').inputValue(), '原输入');
    await page.getByText('技能与上下文', { exact: true }).click();
    assert.deepEqual(JSON.parse(await page.getByLabel('技能参数（JSON）').inputValue()), {
      tone: 'calm',
    });
    await page.locator('#chat-message').fill('private draft');
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('evernight-api-key-change')));
    await page.waitForFunction(() => document.querySelector('#chat-message').value === '');
    assert.ok(!new URL(page.url()).searchParams.has('run'));
    assert.ok(
      await page.evaluate(
        () =>
          !Object.keys(sessionStorage).some((key) =>
            sessionStorage.getItem(key).includes('private draft'),
          ),
      ),
    );

    run.request.skills = [];
    run.skill_revisions = {};
    run.pending_approval_requests = [];
    for (const status of ['finished', 'failed', 'paused']) {
      run.status = status;
      run.metadata = { agent_runtime: { recovery_eligible: false } };
      await page.goto(base);
      await page.getByRole('button', { name: '运行管理', exact: true }).click();
      await page.getByRole('button', { name: '管理运行', exact: true }).click();
      assert.equal(
        await page.getByRole('button', { name: '重试运行', exact: true }).isEnabled(),
        status !== 'finished',
      );
      if (status === 'paused')
        assert.ok(await page.getByRole('button', { name: '继续运行', exact: true }).isDisabled());
    }
    assert.ok(
      await page.locator('body').evaluate((element) => element.scrollWidth <= window.innerWidth),
    );
    assert.deepEqual(errors, []);
    console.log(
      `${width}px: conflicts, refresh, approval/draft retention, failed cancellation, explicit edit/send and fresh approvals passed`,
    );
    await page.close();
  }
} finally {
  await browser.close();
}
