import type { AgentTraceEvent } from '../../api';
import type { ChatToolActivityEntry } from '../chat/chatToolActivity';

const iso = (time: number): string => new Date(time).toISOString();

/**
 * Turns one run's trace into timeline rows: model responses, tool calls and time
 * spent waiting for approval. A model response starts when the run starts or the
 * previous tools finish; after a pause its start is the first text it streamed,
 * so idle time is never counted as model time.
 */
export function runTimelineEntries(trace: AgentTraceEvent[]): ChatToolActivityEntry[] {
  const entries: ChatToolActivityEntry[] = [];
  const toolStarts = new Map<string, number>();
  const approvalStarts = new Map<string, { time: number; name: string }>();
  let modelStart: number | null = null;
  let round = 0;
  const entry = (
    values: Pick<ChatToolActivityEntry, 'key' | 'name' | 'status' | 'statusLabel'> &
      Partial<ChatToolActivityEntry>,
  ): void => {
    entries.push({ needsAttention: false, callText: '', resultText: null, ...values });
  };

  for (const event of [...trace].sort((a, b) => (a.sequence ?? 0) - (b.sequence ?? 0))) {
    const time = event.occurred_at ? Date.parse(event.occurred_at) : NaN;
    if (!Number.isFinite(time)) continue;
    switch (event.event_type) {
      case 'run_started':
        modelStart = time;
        break;
      case 'chat_delta':
        modelStart ??= time;
        break;
      case 'chat_completed':
        round += 1;
        if (modelStart !== null && time >= modelStart) {
          entry({
            key: `model-${round}`,
            name: `模型响应 ${round}`,
            kind: 'model',
            status: 'completed',
            statusLabel: '模型响应',
            startedAt: iso(modelStart),
            finishedAt: iso(time),
          });
        }
        modelStart = null;
        break;
      case 'tool_approval_requested': {
        const request = event.approval_request;
        if (request) approvalStarts.set(request.approval_id, { time, name: request.tool_name });
        break;
      }
      case 'tool_approval_decided': {
        const id = event.approval_decision?.approval_id;
        const waiting = id ? approvalStarts.get(id) : undefined;
        if (id && waiting) {
          approvalStarts.delete(id);
          entry({
            key: `wait-${id}`,
            name: `等待审批 · ${waiting.name}`,
            kind: 'wait',
            status: 'completed',
            statusLabel: '等待审批',
            startedAt: iso(waiting.time),
            finishedAt: iso(time),
          });
        }
        break;
      }
      case 'tool_started':
        if (event.tool_call) toolStarts.set(event.tool_call.tool_call_id, time);
        break;
      case 'tool_completed':
      case 'tool_failed': {
        const call = event.tool_call;
        const id = call?.tool_call_id ?? event.tool_result?.tool_call_id;
        const failed = event.event_type === 'tool_failed';
        const duration = event.metadata?.duration_ms;
        const measured = typeof duration === 'number' && Number.isFinite(duration);
        const started = id ? toolStarts.get(id) : undefined;
        const name = call?.tool_call.name ?? call?.tool_call.tool_name;
        if (id && (started !== undefined || measured)) {
          entry({
            key: `tool-${id}-${event.sequence ?? entries.length}`,
            name: typeof name === 'string' ? name : '工具调用',
            status: failed ? 'failed' : 'completed',
            statusLabel: failed ? '工具失败' : '工具调用',
            startedAt: iso(started ?? time - (duration as number)),
            finishedAt: iso(time),
            durationMs: measured ? (duration as number) : undefined,
          });
          toolStarts.delete(id);
        }
        // The next model call begins once the tools of this round are done.
        modelStart = time;
        break;
      }
      case 'run_paused':
      case 'run_stopped':
        modelStart = null;
        break;
    }
  }
  return entries.sort((a, b) => Date.parse(a.startedAt!) - Date.parse(b.startedAt!));
}

export type RunTimeShare = { model: number; tool: number; wait: number };

/** Time spent per kind of row, in milliseconds. Parallel tools add up. */
export function runTimeShare(entries: ChatToolActivityEntry[]): RunTimeShare {
  const share: RunTimeShare = { model: 0, tool: 0, wait: 0 };
  for (const item of entries) {
    const elapsed =
      item.durationMs ?? Date.parse(item.finishedAt ?? '') - Date.parse(item.startedAt ?? '');
    if (Number.isFinite(elapsed) && elapsed > 0) share[item.kind ?? 'tool'] += elapsed;
  }
  return share;
}
