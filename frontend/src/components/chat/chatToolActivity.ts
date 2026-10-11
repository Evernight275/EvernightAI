import { computed, type ComputedRef } from 'vue';
import type { AgentRunState, AgentTraceEvent, ToolApprovalRequest } from '../../api';
import {
  reconcileRunTranscript,
  toolStatusLabels,
  type ChatTranscriptEntry,
} from '../../domain/chat';

export type ChatToolActivityProps = {
  run: AgentRunState | null;
  trace: AgentTraceEvent[];
  pendingApprovals: ToolApprovalRequest[];
};

export type ChatToolActivityEntry = {
  key: string;
  name: string;
  status: NonNullable<ChatTranscriptEntry['toolActivity']>['status'];
  statusLabel: string;
  /** Failed calls and calls waiting for approval open on their own. */
  needsAttention: boolean;
  startedAt?: string;
  finishedAt?: string;
  durationMs?: number;
  callText: string;
  resultText: string | null;
};

export function useChatToolActivity(props: ChatToolActivityProps): {
  activities: ComputedRef<ChatToolActivityEntry[]>;
  summary: ComputedRef<string>;
} {
  const activities = computed(() => toolActivities(props.run, props.trace, props.pendingApprovals));
  return { activities, summary: computed(() => toolActivitySummary(activities.value)) };
}

/** Counts per status in a fixed order, e.g. "10 完成 · 1 失败"; empty for a single call. */
export function toolActivitySummary(activities: ChatToolActivityEntry[]): string {
  if (activities.length < 2) return '';
  const order = ['completed', 'failed', 'running', 'approval', 'pending', 'canceled'] as const;
  return order
    .map((status) => {
      const count = activities.filter((activity) => activity.status === status).length;
      return count ? `${count} ${toolStatusLabels[status]}` : '';
    })
    .filter(Boolean)
    .join(' · ');
}

export function toolActivities(
  run: AgentRunState | null,
  trace: AgentTraceEvent[] = [],
  pendingApprovals: ToolApprovalRequest[] = [],
): ChatToolActivityEntry[] {
  const snapshot: AgentRunState = {
    run_id: 'details',
    request: { provider_id: '', model_id: '', context_id: '' },
    ...run,
    status:
      run?.status === 'paused' &&
      trace.length &&
      !['run_paused', 'run_stopped'].includes(trace.at(-1)!.event_type)
        ? 'running'
        : run?.status,
    trace: trace.length ? trace : run?.trace,
    pending_approval_requests: pendingApprovals.length
      ? pendingApprovals
      : run?.pending_approval_requests,
  };
  return reconcileRunTranscript([], snapshot).flatMap((entry) => {
    const activity = entry.toolActivity;
    return activity
      ? [
          {
            key: activity.callId,
            name: activity.name,
            status: activity.status,
            statusLabel: toolStatusLabels[activity.status],
            needsAttention: activity.status === 'failed' || activity.status === 'approval',
            startedAt: activity.startedAt,
            finishedAt: activity.finishedAt,
            durationMs: activity.durationMs,
            callText: activity.argumentsText,
            resultText: activity.resultText || null,
          },
        ]
      : [];
  });
}
