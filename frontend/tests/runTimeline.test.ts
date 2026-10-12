import { describe, expect, it } from 'vitest';
import type { AgentTraceEvent } from '../src/api';
import { runTimeShare, runTimelineEntries } from '../src/components/data/runTimeline';
import {
  runFailureItems,
  tokenCost,
  tokenCostsByModel,
  toolFailureItems,
} from '../src/components/data/dataDashboard';

const base = Date.parse('2026-10-11T16:42:00Z');
let sequence = 0;
function event(ms: number, values: Partial<AgentTraceEvent> & Pick<AgentTraceEvent, 'event_type'>) {
  return { sequence: ++sequence, occurred_at: new Date(base + ms).toISOString(), ...values };
}
const call = (id: string, name: string) => ({ tool_call_id: id, tool_call: { name } });
const span = (entry: { startedAt?: string; finishedAt?: string }) => [
  Date.parse(entry.startedAt!) - base,
  Date.parse(entry.finishedAt!) - base,
];

describe('single run timeline', () => {
  it('lays out model responses, tools and approval waits in start order', () => {
    const entries = runTimelineEntries([
      event(0, { event_type: 'run_started' }),
      event(400, { event_type: 'chat_delta' }),
      event(2000, { event_type: 'chat_completed' }),
      event(2000, {
        event_type: 'tool_approval_requested',
        approval_request: { approval_id: 'a1', tool_call_id: 't1', tool_name: 'restricted_shell' },
      }),
      event(2010, { event_type: 'run_paused' }),
      event(9000, {
        event_type: 'tool_approval_decided',
        approval_decision: { approval_id: 'a1', tool_call_id: 't1', status: 'approved' },
      }),
      event(9000, { event_type: 'tool_started', tool_call: call('t1', 'restricted_shell') }),
      event(9500, {
        event_type: 'tool_completed',
        tool_call: call('t1', 'restricted_shell'),
        metadata: { duration_ms: 480 },
      }),
      event(9500, { event_type: 'tool_started', tool_call: call('t2', 'write_text_file') }),
      event(9600, { event_type: 'tool_failed', tool_call: call('t2', 'write_text_file') }),
      event(12000, { event_type: 'chat_completed' }),
      event(12000, { event_type: 'run_stopped' }),
    ]);

    expect(entries.map((entry) => [entry.name, entry.kind, entry.status, ...span(entry)])).toEqual([
      ['模型响应 1', 'model', 'completed', 0, 2000],
      ['等待审批 · restricted_shell', 'wait', 'completed', 2000, 9000],
      ['restricted_shell', undefined, 'completed', 9000, 9500],
      ['write_text_file', undefined, 'failed', 9500, 9600],
      ['模型响应 2', 'model', 'completed', 9600, 12000],
    ]);
    expect(entries[2]?.durationMs).toBe(480);
    expect(runTimeShare(entries)).toEqual({ model: 4400, tool: 580, wait: 7000 });
  });

  it('does not count a pause as model time', () => {
    const entries = runTimelineEntries([
      event(0, { event_type: 'run_started' }),
      event(100, { event_type: 'run_paused' }),
      event(60000, { event_type: 'chat_delta' }),
      event(61000, { event_type: 'chat_completed' }),
    ]);

    expect(entries.map(span)).toEqual([[60000, 61000]]);
  });

  it('skips events without a timestamp and tools that never started', () => {
    expect(
      runTimelineEntries([
        { event_type: 'run_started' },
        { event_type: 'chat_completed', occurred_at: 'invalid' },
        event(500, { event_type: 'tool_completed', tool_call: call('t9', 'x') }),
      ]),
    ).toEqual([]);
  });
});

describe('failure distribution', () => {
  const errors = [
    {
      dimensions: { event_type: 'tool_failed', error_type: 'ToolPolicyError' },
      metrics: { event_count: 9, distinct_run_count: 4 },
    },
    {
      dimensions: { event_type: 'run_stopped', error_type: 'RemoteProtocolError' },
      metrics: { event_count: 2, distinct_run_count: 2 },
    },
    // Runs that stopped normally carry no error type.
    { dimensions: { event_type: 'run_stopped', error_type: null }, metrics: { event_count: 40 } },
    { dimensions: { event_type: 'tool_failed', error_type: null }, metrics: { event_count: 1 } },
  ];

  it('adds stop reasons to exception types without counting a run twice', () => {
    expect(
      runFailureItems(
        [
          { dimensions: { stop_reason: null }, metrics: { run_count: 2 } },
          { dimensions: { stop_reason: 'tool_rounds_exhausted' }, metrics: { run_count: 3 } },
          { dimensions: { stop_reason: 'custom' }, metrics: { run_count: 1 } },
        ],
        errors,
      ),
    ).toEqual([
      { label: '工具轮次用尽', value: 3, note: '停止原因' },
      { label: 'RemoteProtocolError', value: 2, note: '运行因异常中止' },
      { label: 'custom', value: 1, note: '停止原因' },
    ]);
  });

  it('lists tool failures by error type', () => {
    expect(toolFailureItems(errors)).toEqual([
      { label: 'ToolPolicyError', value: 9, note: '涉及 4 次运行' },
      { label: '未记录类型', value: 1, note: undefined },
    ]);
  });
});

describe('token cost', () => {
  it('keeps cache reads unknown when the provider reported no cache usage', () => {
    const cost = tokenCost(
      { metrics: { prompt_tokens_total: 900, cached_prompt_tokens_total: 0 } },
      'm',
    );
    expect(cost.cached).toBeUndefined();
    expect(cost.observed).toBeUndefined();
    expect(cost.prompt).toBe(900);
  });

  it('orders models by total tokens and drops models without usage', () => {
    const row = (model_id: string | null, total: number | null) => ({
      dimensions: { model_id },
      metrics: {
        run_count: 2,
        total_tokens_total: total,
        prompt_tokens_total: total,
        cached_prompt_tokens_total: 10,
        cache_observed_prompt_tokens_total: 40,
      },
    });
    const costs = tokenCostsByModel([row('small', 50), row(null, 400), row('none', null)]);

    expect(costs.map((cost) => [cost.label, cost.total])).toEqual([
      ['未记录模型', 400],
      ['small', 50],
    ]);
    expect(costs[0]).toMatchObject({ cached: 10, observed: 40, runs: 2 });
  });
});
