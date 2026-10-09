import { describe, expect, it } from 'vitest';
import type { AgentRunState, Content } from '../src/api';
import {
  completeStreamedResponse,
  reconcileRunTranscript,
  restoreChatHistory,
} from '../src/domain/chat';

const message = (role: string, text: string): Content => ({
  role,
  content: [{ type: 'text', text }],
});
function run(id: string, offset: number, status = 'finished'): AgentRunState {
  const request = message('user', 'same question');
  const response = { model_id: 'm', message: message('assistant', 'same answer') };
  return {
    run_id: id,
    request: { provider_id: 'p', model_id: 'm', context_id: 'ctx', messages: [request] },
    status,
    response: status === 'finished' ? response : null,
    steps:
      status === 'finished' ? [{ step_type: 'chat', response, message: response.message }] : [],
    trace:
      status === 'finished'
        ? [{ event_type: 'chat_completed', response }]
        : [
            { event_type: 'chat_delta', text_delta: `${id} partial` },
            {
              event_type: 'run_stopped',
              error_type: status === 'failed' ? 'ProviderError' : null,
              error_message: status === 'failed' ? 'provider unavailable' : null,
            },
          ],
    history: {
      message_offset: offset,
      message_indices: status === 'finished' ? [offset, offset + 1] : [],
      started_at: id,
      generation: null,
    },
  };
}

describe('persisted chat history', () => {
  it('restores interrupted runs between committed turns without deduplicating repeated prose', () => {
    const runs = [run('1', 1), run('2', 3, 'canceled'), run('3', 3, 'failed'), run('4', 3)];
    const context = {
      context_id: 'ctx',
      messages: [
        message('assistant', 'imported'),
        message('user', 'same question'),
        message('assistant', 'same answer'),
        message('user', 'same question'),
        message('assistant', 'same answer'),
      ],
    };
    const original = structuredClone(context);
    const entries = restoreChatHistory(context, [...runs].reverse());
    expect(entries.map((entry) => entry.text)).toEqual([
      'imported',
      'same question',
      'same answer',
      'same question',
      '2 partial',
      '请求已取消',
      'same question',
      '3 partial',
      '运行失败：provider unavailable',
      'same question',
      'same answer',
    ]);
    expect(new Set(entries.map((entry) => entry.entryId)).size).toBe(entries.length);
    expect(context).toEqual(original);
  });

  it('matches legacy committed turns in order, including normalized API fields', () => {
    const first = run('1', 0);
    const second = run('3', 2);
    const canceled = run('2', 2, 'canceled');
    for (const item of [first, second, canceled]) {
      item.history = { started_at: item.run_id };
      item.steps = [];
    }
    const context = {
      context_id: 'ctx',
      messages: [
        { ...message('user', 'same question'), metadata: {}, tool_calls: null },
        {
          role: 'assistant',
          content: [{ text: 'same answer', type: 'text', metadata: {}, url: null }],
        },
        message('user', 'same question'),
        message('assistant', 'same answer'),
      ],
    };
    const entries = restoreChatHistory(context, [second, canceled, first]);
    expect(entries.map((entry) => entry.text)).toEqual([
      'same question',
      'same answer',
      'same question',
      '2 partial',
      '请求已取消',
      'same question',
      'same answer',
    ]);
  });

  it('keeps an older focused run in place when its trace and final answer are reconciled again', () => {
    const first = run('1', 0);
    const second = run('2', 2);
    const context = {
      context_id: 'ctx',
      messages: [
        ...first.request.messages!,
        first.response!.message,
        ...second.request.messages!,
        second.response!.message,
      ],
    };
    const entries = restoreChatHistory(context, [first, second]);
    const reconciled = reconcileRunTranscript(entries, first);
    expect(reconciled).toEqual(entries);
    expect(completeStreamedResponse(reconciled, first.response!, first.run_id)).toEqual(entries);
  });

  it('keeps an older tool response and its result in place when focused again', () => {
    const first = run('1', 0);
    const call = {
      tool_call_id: 'read',
      tool_call: { name: 'read_file', arguments: { path: 'a.txt' } },
    };
    first.response!.message.tool_calls = [call];
    const result: Content = {
      role: 'tool',
      tool_call_id: 'read',
      content: [{ type: 'text', text: 'contents' }],
    };
    first.trace!.push({
      event_type: 'tool_completed',
      tool_call: call,
      tool_result: { tool_call_id: 'read', tool_call_result: { content: 'contents' } },
    });
    first.history = { message_offset: 0, message_indices: [0, 1, 2], started_at: '1' };
    const second = run('2', 3);
    const context = {
      context_id: 'ctx',
      messages: [
        ...first.request.messages!,
        first.response!.message,
        result,
        ...second.request.messages!,
        second.response!.message,
      ],
    };
    const entries = restoreChatHistory(context, [first, second]);
    const reconciled = reconcileRunTranscript(entries, first);
    expect(reconciled).toEqual(entries);
    expect(completeStreamedResponse(reconciled, first.response!, first.run_id)).toEqual(entries);
  });

  it('retains context-only tool results when no run snapshot is available', () => {
    const call = {
      tool_call_id: 'read',
      tool_call: { name: 'read_file', arguments: { path: 'a.txt' } },
    };
    const entries = restoreChatHistory(
      {
        context_id: 'ctx',
        messages: [
          message('user', 'read it'),
          { role: 'assistant', tool_calls: [call] },
          {
            role: 'tool',
            tool_call_id: 'read',
            content: [{ type: 'text', text: 'file contents' }],
          },
        ],
      },
      [],
    );
    expect(entries).toHaveLength(2);
    expect(entries[1]?.toolActivity).toMatchObject({
      status: 'completed',
      resultText: 'file contents',
    });
  });

  it('restores a retried failure without repeating the original user question', () => {
    const failed = run('1', 0, 'failed');
    const retried = run('2', 0);
    retried.request.metadata = { retry_of: failed.run_id };
    const entries = restoreChatHistory(
      { context_id: 'ctx', messages: [...retried.request.messages!, retried.response!.message] },
      [failed, retried],
    );
    expect(entries.map((entry) => entry.text)).toEqual([
      'same question',
      '1 partial',
      '运行失败：provider unavailable',
      'same answer',
    ]);
  });

  it.each(['missing source', 'changed request'])('retains retry questions with %s', (caseName) => {
    const failed = run('1', 0, 'failed');
    const retried = run('2', 0);
    retried.request.metadata = { retry_of: failed.run_id };
    if (caseName === 'changed request')
      retried.request.messages = [message('user', 'changed question')];
    const entries = restoreChatHistory(
      { context_id: 'ctx', messages: [...retried.request.messages!, retried.response!.message] },
      caseName === 'missing source' ? [retried] : [failed, retried],
    );
    expect(entries.filter((entry) => entry.role === 'user').map((entry) => entry.text)).toEqual(
      caseName === 'missing source' ? ['same question'] : ['same question', 'changed question'],
    );
  });

  it('does not match different tool arguments when a legacy call contains an explicit null', () => {
    const legacy = run('1', 0);
    const call = { tool_call_id: 'read', tool_call: { name: 'read_file', arguments: {} } };
    const reply = { model_id: 'm', message: { role: 'assistant', tool_calls: [call] } };
    legacy.history = {};
    legacy.response = reply;
    legacy.steps = [];
    legacy.trace = [{ event_type: 'chat_completed', response: reply }];
    const entries = restoreChatHistory(
      {
        context_id: 'ctx',
        messages: [
          ...legacy.request.messages!,
          {
            role: 'assistant',
            tool_calls: [{ ...call, tool_call: { name: 'read_file', arguments: { limit: null } } }],
          },
        ],
      },
      [legacy],
    );
    expect(entries.filter((entry) => entry.toolActivity)).toHaveLength(2);
    expect(entries.find((entry) => entry.toolActivity)?.toolActivity?.argumentsText).toContain(
      'null',
    );
  });

  it('restores a committed tool failure once and retains its error details', () => {
    const failed = run('1', 0, 'failed');
    failed.stop_reason = 'tool_error';
    const call = {
      tool_call_id: 'write',
      tool_call: { name: 'write_file', arguments: { path: 'a.txt' } },
    };
    const answer: Content = { role: 'assistant', tool_calls: [call] };
    const error: Content = {
      role: 'tool',
      tool_call_id: 'write',
      metadata: { error: true },
      content: [{ type: 'text', text: 'permission denied' }],
    };
    failed.steps = [
      { step_type: 'chat', message: answer },
      { step_type: 'tool_error', message: error },
    ];
    failed.trace = [
      {
        event_type: 'tool_failed',
        tool_call: call,
        error_type: 'PermissionError',
        error_message: 'permission denied',
      },
    ];
    failed.history = { message_offset: 0, message_indices: [0, 1, 2] };
    const entries = restoreChatHistory(
      { context_id: 'ctx', messages: [failed.request.messages![0]!, answer, error] },
      [failed],
    );
    expect(entries.filter((entry) => entry.text === 'same question')).toHaveLength(1);
    expect(entries.filter((entry) => entry.toolActivity)).toHaveLength(1);
    expect(entries.find((entry) => entry.toolActivity)?.toolActivity).toMatchObject({
      status: 'failed',
      resultText: 'permission denied',
    });
  });

  it('excludes other contexts and older generations after a chat is cleared', () => {
    const current = run('2', 0, 'canceled');
    current.history = { generation: 'new', message_offset: 0, message_indices: [] };
    const foreign = { ...run('3', 0), request: { ...run('3', 0).request, context_id: 'other' } };
    const entries = restoreChatHistory(
      { context_id: 'ctx', messages: [], metadata: { chat_history_generation: 'new' } },
      [run('1', 0), foreign, current],
    );
    expect(entries.map((entry) => entry.text)).toEqual([
      'same question',
      '2 partial',
      '请求已取消',
    ]);
  });
});
