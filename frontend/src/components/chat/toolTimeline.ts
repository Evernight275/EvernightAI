import type { ChatToolActivityEntry } from './chatToolActivity';
import { toolElapsed } from './toolTiming';

export type ToolTimelineRow = {
  key: string;
  name: string;
  status: ChatToolActivityEntry['status'];
  statusLabel: string;
  /** What the bar stands for; drives its color and the legend. */
  tone: 'tool' | 'model' | 'wait' | 'failed' | 'idle';
  /** Milliseconds from the first call's start. */
  offsetMs: number;
  durationMs: number;
  /** Bar position and length as percentages of the whole span. */
  left: number;
  width: number;
};

export type ToolTimeline = {
  spanMs: number;
  rows: ToolTimelineRow[];
  ticks: { position: number; label: string }[];
};

/**
 * Places each timed call on a shared time axis that starts at the first call.
 * Calls without a start time are left out; fewer than two timed calls is not a
 * timeline, so the result is null.
 */
export function toolTimeline(
  activities: ChatToolActivityEntry[],
  now = Date.now(),
): ToolTimeline | null {
  const timed = activities.flatMap((activity) => {
    const start = activity.startedAt ? Date.parse(activity.startedAt) : NaN;
    if (!Number.isFinite(start)) return [];
    const finish = activity.finishedAt ? Date.parse(activity.finishedAt) : NaN;
    const measured =
      activity.durationMs ??
      (Number.isFinite(finish) ? finish - start : activity.status === 'running' ? now - start : 0);
    const duration = Number.isFinite(measured) ? Math.max(0, measured) : 0;
    return [{ activity, start, duration }];
  });
  if (timed.length < 2) return null;

  const origin = Math.min(...timed.map((item) => item.start));
  const spanMs = Math.max(...timed.map((item) => item.start + item.duration)) - origin;
  if (spanMs <= 0) return null;

  return {
    spanMs,
    rows: timed.map(({ activity, start, duration }) => ({
      key: activity.key,
      name: activity.name,
      status: activity.status,
      statusLabel: activity.statusLabel,
      tone: timelineTone(activity),
      offsetMs: start - origin,
      durationMs: duration,
      left: ((start - origin) / spanMs) * 100,
      width: (duration / spanMs) * 100,
    })),
    ticks: [0, 0.5, 1].map((position) => ({
      position: position * 100,
      label: timeLabel(spanMs * position),
    })),
  };
}

function timelineTone(activity: ChatToolActivityEntry): ToolTimelineRow['tone'] {
  if (activity.kind) return activity.kind;
  if (activity.status === 'failed') return 'failed';
  return ['pending', 'approval', 'canceled'].includes(activity.status) ? 'idle' : 'tool';
}

export function timeLabel(ms: number): string {
  return toolElapsed({ durationMs: ms }) ?? '0';
}
