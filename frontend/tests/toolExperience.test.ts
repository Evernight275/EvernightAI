import { describe, expect, it } from 'vitest';
import { outputParts } from '../src/components/common/outputText';
import { toolElapsed } from '../src/components/chat/toolTiming';
import { approvalItem } from '../src/components/chat/chatRequestStatus';
import { replyOnlySubmission, retryToolNames } from '../src/domain/runRetry';
import { applyChatTrace, reconcileRunTranscript, restoreChatHistory } from '../src/domain/chat';
import type { AgentRunState } from '../src/api';

const call = {
  tool_call_id: 'write',
  tool_call: { name: 'write_text_file', arguments: { path: 'a.txt' } },
};
const request = { provider_id: 'p', model_id: 'm', context_id: 'ctx' };

describe('tool execution experience', () => {
  it('searches literal text without modifying Unicode offsets or executing markup', () => {
    for (const [text, query, matches] of [
      ['Hello HELLO', 'hello', 2],
      ['a.*b.*', '.*', 2],
      ['İ中文a<script>', '中文', 1],
      ['😀 😀', '😀', 2],
      ['x', 'none', 0],
    ] as const) {
      const parts = outputParts(text, query);
      expect(parts.map((part) => part.text).join('')).toBe(text);
      expect(parts.filter((part) => part.match !== undefined)).toHaveLength(matches);
    }
    expect(outputParts('a', '')).toEqual([{ text: 'a' }]);
  });

  it('preserves elapsed execution time through snapshot reconstruction', () => {
    const start = {
      event_type: 'tool_started' as const,
      tool_call: call,
      occurred_at: '2026-10-05T08:00:00Z',
    };
    const end = {
      event_type: 'tool_completed' as const,
      tool_call: call,
      occurred_at: '2026-10-05T08:00:02Z',
      metadata: { duration_ms: 1500 },
    };
    const live = applyChatTrace(applyChatTrace([], start, 'r'), end, 'r');
    const restored = reconcileRunTranscript([], {
      run_id: 'r',
      request,
      status: 'finished',
      trace: [start, end],
    });
    expect(restored[0]?.toolActivity).toEqual(live[0]?.toolActivity);
    expect(toolElapsed(restored[0]!.toolActivity!)).toBe('1.5 秒');
    expect(toolElapsed({ startedAt: start.occurred_at, finishedAt: end.occurred_at })).toBe(
      '2.0 秒',
    );
    expect(
      toolElapsed(
        { startedAt: start.occurred_at, running: true },
        Date.parse(start.occurred_at) + 61000,
      ),
    ).toBe('1 分 1 秒');
    for (const durationMs of [-1, NaN, Infinity]) expect(toolElapsed({ durationMs })).toBeNull();
    expect(toolElapsed({})).toBeNull();
    expect(toolElapsed({ startedAt: 'invalid', running: true })).toBeNull();
  });

  it('shows argv, file operation scope and actual working directory in approvals', () => {
    const approval = approvalItem({
      approval_id: 'a',
      tool_call_id: 'c',
      tool_name: 'restricted_shell',
      metadata: { working_directory: 'src' },
      tool_call: {
        arguments: {
          command: ['python', '-c', 'print("hi")'],
          cwd: 'tests',
          source_path: 'a',
          destination_path: 'b',
          recursive: true,
          overwrite: false,
        },
      },
    });
    expect(approval.targets).toEqual([
      { name: '工作文件夹', value: 'src' },
      { name: '命令', value: `python -c 'print("hi")'` },
      { name: '命令目录', value: 'tests' },
      { name: '来源路径', value: 'a' },
      { name: '目标路径', value: 'b' },
      { name: '递归操作', value: '是' },
      { name: '覆盖已有文件', value: '否' },
    ]);
  });

  it('warns before replay of completed, failed or uncertain tools but not unexecuted approvals', () => {
    const run: AgentRunState = {
      run_id: 'r',
      request,
      status: 'failed',
      trace: [
        { event_type: 'tool_started', tool_call: call },
        { event_type: 'tool_completed', tool_call: call },
        {
          event_type: 'tool_failed',
          tool_call: { tool_call_id: 'image', tool_call: { name: 'generate_image' } },
        },
        {
          event_type: 'tool_approval_requested',
          tool_call: { tool_call_id: 'pending', tool_call: { name: 'delete_file' } },
        },
      ],
    };
    expect(retryToolNames(run)).toEqual(['write_text_file', 'generate_image']);
    expect(
      retryToolNames({ ...run, trace: [], steps: [{ step_type: 'tool', tool_call: call }] }),
    ).toEqual(['write_text_file']);
    expect(retryToolNames({ ...run, status: 'running' })).toEqual([]);
  });

  it('continues from saved results without permitting image or file tools', () => {
    const run: AgentRunState = {
      run_id: 'r',
      request: {
        ...request,
        messages: [{ role: 'user', content: [{ type: 'text', text: '画图并解释' }] }],
        tools: [{ name: 'generate_image', description: 'Draw' }],
        max_tool_rounds: 8,
      },
      status: 'failed',
      trace: [
        {
          event_type: 'tool_completed',
          tool_call: { tool_call_id: 'image', tool_call: { name: 'generate_image' } },
          tool_result: {
            tool_call_id: 'image',
            tool_call_result: { record_id: 'saved-image', status: 'succeeded' },
          },
        },
      ],
    };
    const submission = replyOnlySubmission(run);
    expect(submission.messages?.[0]).toEqual(run.request.messages![0]);
    expect(submission.messages?.at(-1)?.content?.[0]?.text).toContain('saved-image');
    expect(submission.runOptions).toMatchObject({
      tools: [],
      max_tool_rounds: 0,
      write_memory: false,
    });
    expect(run.request.tools).toHaveLength(1);
    expect(run.request.max_tool_rounds).toBe(8);
    const restored = restoreChatHistory({ context_id: 'ctx', messages: [] }, [
      {
        run_id: 'reply',
        status: 'finished',
        request: {
          ...request,
          messages: submission.messages,
          metadata: submission.runOptions?.metadata,
        },
        response: {
          model_id: 'm',
          message: { role: 'assistant', content: [{ type: 'text', text: '图片已生成' }] },
        },
      },
    ]);
    expect(restored.filter((entry) => entry.role === 'user').map((entry) => entry.text)).toEqual([
      submission.text,
    ]);
  });

  it('previews the project override command and its configured directory before approval', () => {
    const approval = {
      approval_id: 'a',
      tool_call_id: 'c',
      tool_name: 'run_project_task',
      tool_call: { arguments: { project: 'web', task: 'test' } },
    };
    const tool = {
      name: 'run_project_task',
      description: 'Run',
      metadata: {
        task_commands: { test: ['pytest'] },
        project_task_commands: { web: { test: ['pnpm', 'test'] } },
        project_roots: { web: '/workspace/web' },
        working_directory: '/workspace',
      },
    };
    expect(approvalItem(approval, undefined, tool).targets).toContainEqual({
      name: '配置命令',
      value: 'pnpm test',
    });
    expect(approvalItem(approval, undefined, tool).targets).toContainEqual({
      name: '任务执行目录',
      value: '/workspace/web',
    });
  });
});
