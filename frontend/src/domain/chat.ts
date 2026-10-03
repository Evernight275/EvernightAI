import type {
  AgentRunState,
  AgentRunRequest,
  AgentTraceEvent,
  ChatResponse,
  Content,
  ChatSkill,
  ToolCall,
  Context,
} from '../api';
import { runFailureError } from './runSkills';

export type ChatSubmission = {
  providerId: string;
  modelId: string;
  text: string;
  skills?: ChatSkill[];
  workingDirectory?: string;
  messages?: Content[];
  runOptions?: Partial<AgentRunRequest>;
};

export type ChatTranscriptEntry = {
  entryId: string;
  role: string;
  text: string;
  content: Content;
  modelId?: string | null;
  finishReason?: string | null;
  streamRunId?: string;
  streaming?: boolean;
  runNotice?: 'canceled' | 'failed';
  toolActivity?: {
    callId: string;
    name: string;
    status: 'pending' | 'approval' | 'running' | 'completed' | 'failed' | 'canceled';
    argumentsText: string;
    resultText?: string;
    errorType?: string;
    notice?: string;
  };
};

export function userEntry(submission: ChatSubmission, index: number): ChatTranscriptEntry {
  return {
    entryId: `user-${index}`,
    role: 'user',
    text: submission.text,
    content: {
      role: 'user',
      content: [{ type: 'text', text: submission.text }],
    },
    modelId: submission.modelId,
  };
}

export function assistantEntry(response: ChatResponse, index: number): ChatTranscriptEntry {
  return {
    entryId: response.response_id || `assistant-${index}`,
    role: response.message.role || 'assistant',
    text: textFromContent(response.message),
    content: response.message,
    modelId: response.model_id,
    finishReason: response.finish_reason,
  };
}

export function transcriptFromMessages(messages: Content[]): ChatTranscriptEntry[] {
  let entries: ChatTranscriptEntry[] = [];
  for (const [index, content] of messages.entries()) {
    const text = visibleTextFromContent(content);
    if (['user', 'assistant'].includes(content.role) && text) {
      entries.push({ entryId: messageEntryId(content, index), role: content.role, text, content });
    }
    if (content.role === 'assistant') {
      for (const call of content.tool_calls || [])
        entries = upsertTool(
          entries,
          call,
          'history',
          'pending',
          undefined,
          false,
          undefined,
          '结果尚未确认',
        );
    }
    if (content.role === 'tool' && content.tool_call_id) {
      entries = upsertTool(
        entries,
        {
          tool_call_id: content.tool_call_id,
          tool_call: content.name ? { name: content.name } : {},
        },
        'history',
        content.metadata?.error || content.status === 'error' ? 'failed' : 'completed',
        text,
      );
    }
  }
  return entries;
}

function messageEntryId(content: Content, index: number): string {
  const metadataId = content.metadata?.message_id;
  return typeof metadataId === 'string' && metadataId ? metadataId : `${content.role}-${index + 1}`;
}

function textFromContent(message: Content): string {
  return visibleTextFromContent(message) || '[没有文本内容]';
}

function visibleTextFromContent(message: Content): string {
  return (message.content || [])
    .map((part) => part.text)
    .filter((value): value is string => typeof value === 'string')
    .join('\n');
}

export function applyChatTrace(
  entries: ChatTranscriptEntry[],
  event: AgentTraceEvent,
  runId: string,
): ChatTranscriptEntry[] {
  if (event.event_type === 'chat_completed' && event.response) {
    return completeStreamedResponse(entries, event.response, runId);
  }
  const call =
    event.tool_call ||
    (event.approval_request
      ? {
          tool_call_id: event.approval_request.tool_call_id,
          tool_call: event.approval_request.tool_call || { name: event.approval_request.tool_name },
        }
      : undefined);
  if (
    call &&
    [
      'tool_started',
      'tool_completed',
      'tool_failed',
      'tool_approval_requested',
      'tool_approval_decided',
    ].includes(event.event_type)
  ) {
    const status =
      event.event_type === 'tool_started'
        ? 'running'
        : event.event_type === 'tool_completed'
          ? 'completed'
          : event.event_type === 'tool_failed'
            ? 'failed'
            : event.event_type === 'tool_approval_requested'
              ? 'approval'
              : event.approval_decision?.status === 'approved' || event.metadata?.allowed === true
                ? 'pending'
                : 'failed';
    return upsertTool(
      entries,
      call,
      runId,
      status,
      event.error_message ||
        (event.tool_result
          ? JSON.stringify(event.tool_result.tool_call_result, null, 2)
          : status === 'failed'
            ? event.event_type === 'tool_failed'
              ? '工具执行失败'
              : '调用未获批准'
            : undefined),
      false,
      event.error_type || undefined,
    );
  }
  if (event.event_type !== 'chat_delta' || !event.text_delta) return entries;
  const last = entries.at(-1);
  const continuing = last?.streamRunId === runId && last.streaming && !last.toolActivity;
  const text = (continuing ? last.text : '') + event.text_delta;
  const entry: ChatTranscriptEntry = {
    entryId: continuing ? last.entryId : `stream-${runId}-${entries.length}`,
    role: 'assistant',
    text,
    streamRunId: runId,
    streaming: true,
    content: { role: 'assistant', content: [{ type: 'text', text }] },
  };
  return continuing ? [...entries.slice(0, -1), entry] : [...entries, entry];
}

export function completeStreamedResponse(
  entries: ChatTranscriptEntry[],
  response: ChatResponse,
  runId: string,
): ChatTranscriptEntry[] {
  const end = lastIndex(entries, (item) => item.streamRunId === runId);
  const trailing = end < 0 ? [] : entries.slice(end + 1);
  if (end >= 0) entries = entries.slice(0, end + 1);
  let result = entries;
  const last = entries.filter((item) => item.streamRunId === runId).at(-1);
  const text = visibleTextFromContent(response.message);
  const entry = {
    ...assistantEntry(response, entries.length + 1),
    entryId: response.response_id
      ? `${runId}-response-${response.response_id}`
      : `${runId}-assistant-${entries.length + 1}`,
    streamRunId: runId,
    streaming: false,
  };
  const previous = [...entries]
    .reverse()
    .find((item) => item.streamRunId === runId && !item.toolActivity && !item.runNotice);
  const alreadyCompleted =
    previous?.streamRunId === runId &&
    !previous.streaming &&
    ((response.response_id && previous.entryId === entry.entryId) ||
      (previous.text === text &&
        (last === previous ||
          (!!response.message.tool_calls?.length &&
            response.message.tool_calls.every((call) =>
              entries.some(
                (item) =>
                  item.streamRunId === runId && item.toolActivity?.callId === call.tool_call_id,
              ),
            )))));
  if (last?.streamRunId === runId && last.streaming && !last.toolActivity) {
    result = text
      ? [...entries.slice(0, -1), { ...entry, entryId: last.entryId }]
      : entries.slice(0, -1);
  } else if (text && !alreadyCompleted) {
    result = [...entries, entry];
  }
  for (const call of response.message.tool_calls || [])
    result = upsertTool(result, call, runId, 'pending', undefined, true);
  return [...result, ...trailing];
}

function upsertTool(
  entries: ChatTranscriptEntry[],
  call: ToolCall,
  runId: string,
  status: NonNullable<ChatTranscriptEntry['toolActivity']>['status'],
  resultText?: string,
  preserveStatus = false,
  errorType?: string,
  notice?: string,
): ChatTranscriptEntry[] {
  const turnStart = lastIndex(entries, (entry) => entry.role === 'user');
  const index = lastIndex(
    entries,
    (entry, i) =>
      i > turnStart &&
      entry.toolActivity?.callId === call.tool_call_id &&
      entry.streamRunId === runId,
  );
  const previous = index >= 0 ? entries[index] : undefined;
  const previousActivity = previous?.toolActivity;
  if (previousActivity && preserveStatus) return entries;
  const name = call.tool_call.name || call.tool_call.tool_name;
  const args = call.tool_call.arguments ?? call.tool_call.args;
  const activity: NonNullable<ChatTranscriptEntry['toolActivity']> = {
    callId: call.tool_call_id,
    name: typeof name === 'string' ? name : previousActivity?.name || '工具调用',
    status,
    errorType,
    notice,
    argumentsText:
      args === undefined ? previousActivity?.argumentsText || '{}' : JSON.stringify(args, null, 2),
    resultText: resultText ?? previousActivity?.resultText,
  };
  const entry: ChatTranscriptEntry = {
    entryId: previous?.entryId || `tool-${runId}-${entries.length}-${call.tool_call_id}`,
    role: 'tool',
    text: '',
    content: { role: 'tool', tool_call_id: call.tool_call_id },
    streamRunId: runId,
    toolActivity: activity,
  };
  return index < 0 ? [...entries, entry] : entries.map((item, i) => (i === index ? entry : item));
}

function lastIndex(
  entries: ChatTranscriptEntry[],
  matches: (entry: ChatTranscriptEntry, index: number) => boolean,
): number {
  for (let index = entries.length - 1; index >= 0; index--) {
    if (matches(entries[index]!, index)) return index;
  }
  return -1;
}

export const toolStatusLabels = {
  pending: '准备',
  approval: '审批',
  running: '执行中',
  completed: '完成',
  failed: '失败',
  canceled: '已取消',
};

export function reconcileRunTranscript(
  entries: ChatTranscriptEntry[],
  run: AgentRunState,
): ChatTranscriptEntry[] {
  const events: AgentTraceEvent[] = run.trace?.length
    ? run.trace
    : (run.steps || []).flatMap<AgentTraceEvent>((step) => {
        if (step.step_type === 'chat' && step.response)
          return [{ ...step, event_type: 'chat_completed' as const }];
        if (step.step_type === 'tool') return [{ ...step, event_type: 'tool_completed' as const }];
        if (step.step_type === 'tool_error')
          return [{ ...step, event_type: 'tool_failed' as const }];
        return [];
      });
  let result = entries;
  let trailing: ChatTranscriptEntry[] = [];
  if (!events.length) {
    const lastEntry = [...entries].reverse().find((entry) => entry.streamRunId === run.run_id);
    const last = lastEntry ? entries.indexOf(lastEntry) : -1;
    if (last >= 0) {
      result = entries.slice(0, last + 1);
      trailing = entries.slice(last + 1);
    }
  }
  if (events.length) {
    const first = entries.findIndex((entry) => entry.streamRunId === run.run_id);
    trailing =
      first < 0 ? [] : entries.slice(first).filter((entry) => entry.streamRunId !== run.run_id);
    result = first < 0 ? entries : entries.slice(0, first);
    const seen = new Set<number>();
    for (const event of events) {
      if (event.sequence != null && seen.has(event.sequence)) continue;
      if (event.sequence != null) seen.add(event.sequence);
      result = applyChatTrace(result, event, run.run_id);
    }
  }
  for (const approval of run.pending_approval_requests || []) {
    const recorded = [...result]
      .reverse()
      .find(
        (entry) =>
          entry.streamRunId === run.run_id && entry.toolActivity?.callId === approval.tool_call_id,
      )?.toolActivity;
    if (recorded && ['running', 'completed', 'failed', 'canceled'].includes(recorded.status))
      continue;
    if (
      recorded?.status === 'pending' &&
      events.some(
        (event) =>
          event.event_type === 'tool_approval_decided' &&
          (event.tool_call?.tool_call_id || event.approval_decision?.tool_call_id) ===
            approval.tool_call_id,
      )
    )
      continue;
    result = applyChatTrace(
      result,
      { event_type: 'tool_approval_requested', approval_request: approval },
      run.run_id,
    );
  }
  if (run.status && run.status !== 'running') {
    result = result.map((entry) =>
      entry.streamRunId !== run.run_id
        ? entry
        : {
            ...entry,
            streaming: false,
            toolActivity:
              entry.toolActivity &&
              !['completed', 'failed', 'canceled'].includes(entry.toolActivity.status) &&
              !(
                entry.toolActivity.status === 'approval' &&
                run.status === 'paused' &&
                run.pending_approval_requests?.some(
                  (approval) => approval.tool_call_id === entry.toolActivity?.callId,
                )
              )
                ? {
                    ...entry.toolActivity,
                    status:
                      run.status === 'canceled' && entry.toolActivity.status === 'approval'
                        ? 'canceled'
                        : 'pending',
                    notice:
                      run.status === 'paused'
                        ? '运行已暂停，等待继续'
                        : run.status === 'canceled' && entry.toolActivity.status === 'approval'
                          ? '审批已取消，工具未执行'
                          : '运行已停止，结果尚未确认',
                  }
                : entry.toolActivity,
          },
    );
  }
  result = result.filter((entry) => !(entry.streamRunId === run.run_id && entry.runNotice));
  if (run.status === 'canceled' || run.status === 'failed') {
    const failure =
      runFailureError(run)?.message ||
      [...(run.trace || [])].reverse().find((event) => event.error_message)?.error_message ||
      (
        { tool_error: '工具调用失败', tool_rounds_exhausted: '工具调用轮次已达上限' } as Record<
          string,
          string
        >
      )[run.stop_reason || ''] ||
      '原因未知';
    const text = run.status === 'canceled' ? '请求已取消' : `运行失败：${failure}`;
    result.push({
      entryId: `${run.run_id}-status`,
      role: 'system',
      text,
      content: { role: 'system', content: [{ type: 'text', text }] },
      streamRunId: run.run_id,
      runNotice: run.status,
    });
  }
  return [...result, ...trailing];
}

export function restoreChatHistory(context: Context, runs: AgentRunState[]): ChatTranscriptEntry[] {
  const messages = context.messages || [];
  const generation = context.metadata?.chat_history_generation ?? null;
  const claimed = new Set<number>();
  const history = runs
    .filter(
      (run) =>
        run.request.context_id === context.context_id &&
        ((run.metadata?.agent_runtime as Record<string, unknown> | undefined)
          ?.context_history_generation ?? null) === generation,
    )
    .map((run) => {
      const runtime = run.metadata?.agent_runtime as Record<string, unknown> | undefined;
      const indices = Array.isArray(runtime?.context_message_indices)
        ? runtime.context_message_indices.filter(
            (index): index is number =>
              Number.isInteger(index) && index >= 0 && index < messages.length,
          )
        : [];
      return {
        run,
        indices,
        offset:
          typeof runtime?.context_message_offset === 'number'
            ? runtime.context_message_offset
            : messages.length,
      };
    })
    .sort((a, b) => runHistoryTime(a.run).localeCompare(runHistoryTime(b.run)));
  // Older snapshots have no commit positions. Match complete committed turns in order.
  let cursor = 0;
  for (const item of history) {
    const runtime = item.run.metadata?.agent_runtime as Record<string, unknown> | undefined;
    if (
      !Array.isArray(runtime?.context_message_indices) &&
      (item.run.status === 'finished' ||
        ['tool_error', 'tool_rounds_exhausted'].includes(item.run.stop_reason || ''))
    ) {
      let replies = (item.run.steps || [])
        .filter((step) => ['chat', 'tool', 'tool_error'].includes(step.step_type))
        .flatMap((step) =>
          step.message ? [step.message] : step.response ? [step.response.message] : [],
        );
      if (!replies.length)
        replies = (item.run.trace || []).flatMap((event) =>
          event.message
            ? [event.message]
            : event.event_type === 'chat_completed' && event.response
              ? [event.response.message]
              : [],
        );
      if (!replies.length && item.run.response) replies = [item.run.response.message];
      const committed = [...(item.run.request.messages || []), ...replies];
      if (committed.length) {
        for (let start = cursor; start + committed.length <= messages.length; start++) {
          if (committed.every((message, index) => sameMessage(message, messages[start + index]!))) {
            item.indices = committed.map((_, index) => start + index);
            cursor = start + committed.length;
            break;
          }
        }
      }
    }
    if (item.indices.length) item.offset = Math.min(...item.indices);
    item.offset = Math.max(0, Math.min(messages.length, item.offset));
    for (const index of item.indices) claimed.add(index);
  }
  // Place interrupted turns before the next committed turn when legacy offsets are missing.
  for (let i = history.length - 2; i >= 0; i--) {
    const item = history[i]!;
    const runtime = item.run.metadata?.agent_runtime as Record<string, unknown> | undefined;
    if (!item.indices.length && typeof runtime?.context_message_offset !== 'number')
      item.offset = history[i + 1]!.offset;
  }
  let result: ChatTranscriptEntry[] = [];
  const displayedRequests = new Map<string, Content[]>();
  let stored: Content[] = [];
  let storedOffset = 0;
  function flushStored() {
    result.push(
      ...transcriptFromMessages(stored).map((entry, position) => ({
        ...entry,
        entryId: `context-${storedOffset}-${position}`,
      })),
    );
    stored = [];
  }
  for (let index = 0; index <= messages.length; index++) {
    for (const { run } of history.filter((item) => item.offset === index)) {
      flushStored();
      const messages = run.request.messages || [];
      const retryOf = run.request.metadata?.retry_of;
      const source = typeof retryOf === 'string' ? displayedRequests.get(retryOf) : undefined;
      const repeatedRetry =
        source &&
        source.length === messages.length &&
        source.every((message, position) => sameMessage(message, messages[position]!));
      const request = transcriptFromMessages(repeatedRetry ? [] : messages).map(
        (entry, position) => ({
          ...entry,
          entryId: `${run.run_id}-request-${position}`,
        }),
      );
      let turn = reconcileRunTranscript(request, run);
      if (run.status === 'finished' && run.response)
        turn = completeStreamedResponse(turn, run.response, run.run_id);
      result.push(...turn);
      displayedRequests.set(run.run_id, messages);
    }
    if (index < messages.length && !claimed.has(index)) {
      if (!stored.length) storedOffset = index;
      stored.push(messages[index]!);
    }
  }
  flushStored();
  return result;
}

function sameMessage(a: Content, b: Content): boolean {
  const key = (message: Content) =>
    JSON.stringify(
      [
        message.role,
        message.status ?? null,
        message.metadata?.error ?? null,
        (message.content || []).map((part) => [
          part.type,
          part.text ?? null,
          part.url ?? null,
          part.data ?? null,
          part.mime_type ?? null,
          part.detail ?? null,
          part.metadata || {},
        ]),
        (message.tool_calls || []).map((call) => [
          call.tool_call_id,
          call.tool_call,
          call.approval
            ? [
                call.approval.approval_id,
                call.approval.tool_call_id,
                call.approval.status,
                call.approval.reason ?? null,
                call.approval.metadata || {},
              ]
            : null,
          call.metadata || {},
        ]),
        message.tool_call_id ?? null,
        message.name ?? null,
      ],
      (_, value) =>
        value && typeof value === 'object' && !Array.isArray(value)
          ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)))
          : value,
    );
  return key(a) === key(b);
}

export function runHistoryTime(run: AgentRunState): string {
  const runtime = run.metadata?.agent_runtime as Record<string, unknown> | undefined;
  return typeof runtime?.history_started_at === 'string'
    ? runtime.history_started_at
    : run.trace?.[0]?.occurred_at || '';
}
