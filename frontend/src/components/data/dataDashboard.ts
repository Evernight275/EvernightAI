import type { DataFilter, DataStatisticsRequest, DataStatisticsRow } from '../../api';
import type { DataBarItem } from './DataBarList.vue';

export type DashboardRange = '7' | '30' | 'all';

export const dashboardRanges: { id: DashboardRange; label: string }[] = [
  { id: '7', label: '近 7 天' },
  { id: '30', label: '近 30 天' },
  { id: 'all', label: '全部' },
];

export type DashboardQuery =
  'runs' | 'runsByDay' | 'runsByModel' | 'events' | 'tools' | 'runFailures' | 'errors';

export type DayValue = { day: string; value: number };

// The runtime sources store days as UTC "YYYY-MM-DD" text, so ranges compare as strings.
export function rangeStart(range: DashboardRange, now = new Date()): string | undefined {
  if (range === 'all') return;
  const start = new Date(now);
  start.setUTCDate(start.getUTCDate() - (Number(range) - 1));
  return start.toISOString().slice(0, 10);
}

export function dashboardRequests(
  range: DashboardRange,
  now = new Date(),
): Record<DashboardQuery, DataStatisticsRequest> {
  const start = rangeStart(range, now);
  const since = (field: string): DataFilter[] =>
    start ? [{ field_id: field, operator: 'greater_than_or_equals', value: start }] : [];
  return {
    runs: {
      source_id: 'agent_runs',
      metrics: [
        'run_count',
        'successful_run_rate',
        'failed_run_rate',
        'distinct_session_count',
        'total_tokens_total',
        'prompt_tokens_total',
        'completion_tokens_total',
        'cached_prompt_tokens_total',
        'cache_observed_prompt_tokens_total',
      ],
      filters: since('created_day'),
    },
    runsByDay: {
      source_id: 'agent_runs',
      metrics: ['run_count', 'total_tokens_total'],
      dimensions: ['created_day'],
      filters: since('created_day'),
      sorts: [{ field_id: 'created_day', direction: 'asc' }],
    },
    runsByModel: {
      source_id: 'agent_runs',
      metrics: [
        'run_count',
        'total_tokens_total',
        'successful_run_rate',
        'prompt_tokens_total',
        'completion_tokens_total',
        'cached_prompt_tokens_total',
        'cache_observed_prompt_tokens_total',
      ],
      dimensions: ['model_id'],
      filters: since('created_day'),
      sorts: [{ field_id: 'run_count', direction: 'desc' }],
      limit: 8,
    },
    events: {
      source_id: 'agent_trace_events',
      metrics: ['tool_call_count', 'tool_failure_count', 'tool_approval_required_count'],
      filters: since('event_day'),
    },
    tools: {
      source_id: 'agent_trace_events',
      metrics: ['tool_call_count', 'tool_failure_count'],
      dimensions: ['tool_name'],
      filters: since('event_day'),
      sorts: [{ field_id: 'tool_call_count', direction: 'desc' }],
      limit: 20,
    },
    runFailures: {
      source_id: 'agent_runs',
      metrics: ['run_count'],
      dimensions: ['stop_reason'],
      filters: [
        ...since('created_day'),
        { field_id: 'is_failed', operator: 'equals', value: true },
      ],
      sorts: [{ field_id: 'run_count', direction: 'desc' }],
    },
    errors: {
      source_id: 'agent_trace_events',
      metrics: ['event_count', 'distinct_run_count'],
      dimensions: ['event_type', 'error_type'],
      filters: [
        ...since('event_day'),
        { field_id: 'event_type', operator: 'in', value: ['tool_failed', 'run_stopped'] },
      ],
      sorts: [{ field_id: 'event_count', direction: 'desc' }],
      limit: 50,
    },
  };
}

const stopReasonLabels: Record<string, string> = {
  tool_rounds_exhausted: '工具轮次用尽',
  tool_error: '工具错误',
};

/**
 * Why runs failed. A run that ends on an exception records the error type on its
 * stop event and no stop reason; a run that ends on a stop reason records no
 * error type. The two sets are disjoint, so their counts add up.
 */
export function runFailureItems(
  runFailures: DataStatisticsRow[],
  errors: DataStatisticsRow[],
): DataBarItem[] {
  const byReason = runFailures.flatMap((row) => {
    const reason = row.dimensions?.stop_reason;
    const count = metric(row, 'run_count') ?? 0;
    return typeof reason === 'string' && reason && count
      ? [{ label: stopReasonLabels[reason] ?? reason, value: count, note: '停止原因' }]
      : [];
  });
  const byError = errors.flatMap((row) => {
    const type = row.dimensions?.error_type;
    const count = metric(row, 'distinct_run_count') ?? metric(row, 'event_count') ?? 0;
    return row.dimensions?.event_type === 'run_stopped' && typeof type === 'string' && type && count
      ? [{ label: type, value: count, note: '运行因异常中止' }]
      : [];
  });
  return [...byReason, ...byError].sort((a, b) => b.value - a.value);
}

export function toolFailureItems(errors: DataStatisticsRow[]): DataBarItem[] {
  return errors
    .flatMap((row) => {
      const count = metric(row, 'event_count') ?? 0;
      if (row.dimensions?.event_type !== 'tool_failed' || !count) return [];
      const type = row.dimensions?.error_type;
      const runs = metric(row, 'distinct_run_count');
      return [
        {
          label: typeof type === 'string' && type ? type : '未记录类型',
          value: count,
          note: runs === undefined ? undefined : `涉及 ${compactNumber(runs)} 次运行`,
        },
      ];
    })
    .sort((a, b) => b.value - a.value);
}

export type TokenCost = {
  label: string;
  runs: number | undefined;
  prompt: number | undefined;
  completion: number | undefined;
  total: number | undefined;
  /** Cache-read input tokens, only where the provider reported cache usage. */
  cached: number | undefined;
  /** Input tokens that came with cache usage; the base for the cache-read share. */
  observed: number | undefined;
};

export function tokenCost(row: DataStatisticsRow | undefined, label: string): TokenCost {
  const observed = metric(row, 'cache_observed_prompt_tokens_total');
  return {
    label,
    runs: metric(row, 'run_count'),
    prompt: metric(row, 'prompt_tokens_total'),
    completion: metric(row, 'completion_tokens_total'),
    total: metric(row, 'total_tokens_total'),
    // Without observed cache usage a cached count is unknown, not zero.
    cached: observed ? metric(row, 'cached_prompt_tokens_total') : undefined,
    observed: observed || undefined,
  };
}

export function tokenCostsByModel(rows: DataStatisticsRow[]): TokenCost[] {
  return rows
    .map((row) => tokenCost(row, String(row.dimensions?.model_id || '未记录模型')))
    .filter((cost) => (cost.total ?? 0) > 0)
    .sort((a, b) => (b.total ?? 0) - (a.total ?? 0));
}

// Aggregates over no rows come back as null; that is unknown, not zero.
export function metric(row: DataStatisticsRow | undefined, id: string): number | undefined {
  const value = row?.metrics?.[id];
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

export function compactNumber(value: number | undefined): string {
  if (value === undefined) return '—';
  const size = Math.abs(value);
  for (const [limit, unit] of [
    [1e9, 'B'],
    [1e6, 'M'],
    [1e4, 'K'],
  ] as const) {
    if (size >= limit) {
      const scaled = value / (unit === 'K' ? 1e3 : limit);
      return `${scaled.toFixed(Math.abs(scaled) >= 100 ? 0 : 1).replace(/\.0$/, '')}${unit}`;
    }
  }
  return Number.isInteger(value)
    ? value.toLocaleString('en-US')
    : value.toLocaleString('en-US', { maximumFractionDigits: 1 });
}

export function percentText(value: number | undefined): string {
  if (value === undefined) return '—';
  return `${(value * 100).toFixed(value > 0 && value < 0.1 ? 1 : 0)}%`;
}

export function ratio(part: number | undefined, whole: number | undefined): number | undefined {
  return part === undefined || !whole ? undefined : part / whole;
}

// One entry per day, including days without runs, so gaps in activity stay visible.
export function dailySeries(
  rows: DataStatisticsRow[],
  metricId: string,
  range: DashboardRange,
  now = new Date(),
): DayValue[] {
  const values = new Map<string, number>();
  for (const row of rows) {
    const day = row.dimensions?.created_day;
    if (typeof day === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(day))
      values.set(day, metric(row, metricId) ?? 0);
  }
  const first = rangeStart(range, now) ?? [...values.keys()].sort()[0];
  if (!first) return [];
  const last = now.toISOString().slice(0, 10);
  const series: DayValue[] = [];
  const cursor = new Date(`${first}T00:00:00Z`);
  while (cursor.toISOString().slice(0, 10) <= last) {
    const day = cursor.toISOString().slice(0, 10);
    series.push({ day, value: values.get(day) ?? 0 });
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return series;
}

// A round axis maximum: 1, 2 or 5 times a power of ten.
export function axisMaximum(value: number): number {
  if (value <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  const step = [1, 2, 5, 10].find((candidate) => candidate * power >= value) ?? 10;
  return step * power;
}
