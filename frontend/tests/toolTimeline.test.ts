import { describe, expect, it } from 'vitest';
import type { ChatToolActivityEntry } from '../src/components/chat/chatToolActivity';
import { toolTimeline } from '../src/components/chat/toolTimeline';

const base = Date.parse('2026-10-11T16:42:00Z');
const at = (ms: number) => new Date(base + ms).toISOString();

function call(key: string, overrides: Partial<ChatToolActivityEntry> = {}): ChatToolActivityEntry {
  return {
    key,
    name: key,
    status: 'completed',
    statusLabel: '完成',
    needsAttention: false,
    callText: '{}',
    resultText: null,
    ...overrides,
  };
}

describe('tool timeline', () => {
  it('places calls on one axis that starts at the first call', () => {
    const timeline = toolTimeline([
      call('list', { startedAt: at(0), durationMs: 1000 }),
      call('shell', { startedAt: at(2000), finishedAt: at(4000) }),
      call('write', { startedAt: at(6000), durationMs: 2000, status: 'failed' }),
    ])!;

    expect(timeline.spanMs).toBe(8000);
    expect(timeline.rows.map(({ key, left, width }) => [key, left, width])).toEqual([
      ['list', 0, 12.5],
      ['shell', 25, 25],
      ['write', 75, 25],
    ]);
    expect(timeline.rows[1]).toMatchObject({ offsetMs: 2000, durationMs: 2000 });
    expect(timeline.ticks.map((tick) => tick.label)).toEqual(['0', '4.0 秒', '8.0 秒']);
  });

  it('prefers the reported duration over event timestamps', () => {
    const timeline = toolTimeline([
      call('a', { startedAt: at(0), finishedAt: at(5000), durationMs: 40 }),
      call('b', { startedAt: at(960), durationMs: 40 }),
    ])!;

    expect(timeline.spanMs).toBe(1000);
    expect(timeline.rows[0]).toMatchObject({ durationMs: 40, width: 4 });
  });

  it('extends a running call to the current time', () => {
    const timeline = toolTimeline(
      [
        call('done', { startedAt: at(0), durationMs: 500 }),
        call('live', { startedAt: at(1000), status: 'running' }),
      ],
      base + 4000,
    )!;

    expect(timeline.spanMs).toBe(4000);
    expect(timeline.rows[1]).toMatchObject({ left: 25, width: 75, durationMs: 3000 });
  });

  it('leaves out calls without a usable start time', () => {
    const timeline = toolTimeline([
      call('a', { startedAt: at(0), durationMs: 100 }),
      call('pending', { status: 'approval' }),
      call('broken', { startedAt: 'invalid', durationMs: 100 }),
      call('b', { startedAt: at(900), durationMs: 100 }),
    ])!;

    expect(timeline.rows.map((row) => row.key)).toEqual(['a', 'b']);
  });

  it('is not a timeline with fewer than two timed calls or no elapsed time', () => {
    expect(toolTimeline([])).toBeNull();
    expect(toolTimeline([call('only', { startedAt: at(0), durationMs: 100 })])).toBeNull();
    expect(
      toolTimeline([call('a', { startedAt: at(0) }), call('b', { startedAt: at(0) })]),
    ).toBeNull();
  });
});
