import { describe, expect, it } from 'vitest';
import {
  axisMaximum,
  compactNumber,
  dailySeries,
  dashboardRequests,
  metric,
  percentText,
  rangeStart,
  ratio,
} from '../src/components/data/dataDashboard';

const now = new Date('2026-10-10T03:00:00Z');

describe('data dashboard', () => {
  it('limits every query to the selected UTC day range', () => {
    expect(rangeStart('7', now)).toBe('2026-10-04');
    expect(rangeStart('30', now)).toBe('2026-09-11');
    expect(rangeStart('all', now)).toBeUndefined();

    const recent = dashboardRequests('7', now);
    expect(recent.runs.filters).toEqual([
      { field_id: 'created_day', operator: 'greater_than_or_equals', value: '2026-10-04' },
    ]);
    expect(recent.tools.filters?.[0]?.field_id).toBe('event_day');
    expect(
      Object.values(dashboardRequests('all', now)).every((item) => !item.filters?.length),
    ).toBe(true);
  });

  it('keeps missing aggregates unknown instead of zero', () => {
    const row = { metrics: { run_count: 3, cached: null, text: 'x' } };
    expect(metric(row, 'run_count')).toBe(3);
    expect(metric(row, 'cached')).toBeUndefined();
    expect(metric(row, 'text')).toBeUndefined();
    expect(metric(undefined, 'run_count')).toBeUndefined();
    expect(ratio(5, undefined)).toBeUndefined();
    expect(ratio(5, 0)).toBeUndefined();
    expect(ratio(undefined, 10)).toBeUndefined();
    expect(ratio(5, 20)).toBe(0.25);
    expect(compactNumber(undefined)).toBe('—');
    expect(percentText(undefined)).toBe('—');
  });

  it('formats counts, large totals and rates for tiles', () => {
    expect(compactNumber(0)).toBe('0');
    expect(compactNumber(1284)).toBe('1,284');
    expect(compactNumber(12900)).toBe('12.9K');
    expect(compactNumber(223500)).toBe('224K');
    expect(compactNumber(3764396)).toBe('3.8M');
    expect(compactNumber(2.345)).toBe('2.3');
    expect(percentText(0.8125)).toBe('81%');
    expect(percentText(0.0625)).toBe('6.3%');
    expect(percentText(0)).toBe('0%');
    expect(percentText(1)).toBe('100%');
  });

  it('builds one entry per day and keeps idle days visible', () => {
    const rows = [
      { dimensions: { created_day: '2026-10-08' }, metrics: { run_count: 4 } },
      { dimensions: { created_day: '2026-10-10' }, metrics: { run_count: 2 } },
      { dimensions: { created_day: null }, metrics: { run_count: 9 } },
    ];
    const week = dailySeries(rows, 'run_count', '7', now);
    expect(week).toHaveLength(7);
    expect(week[0]).toEqual({ day: '2026-10-04', value: 0 });
    expect(week.slice(-3)).toEqual([
      { day: '2026-10-08', value: 4 },
      { day: '2026-10-09', value: 0 },
      { day: '2026-10-10', value: 2 },
    ]);
    expect(dailySeries(rows, 'run_count', 'all', now).map((item) => item.day)).toEqual([
      '2026-10-08',
      '2026-10-09',
      '2026-10-10',
    ]);
    expect(dailySeries([], 'run_count', 'all', now)).toEqual([]);
  });

  it('rounds the value axis up to a clean maximum', () => {
    expect([0, 1, 3, 9, 10, 131000].map(axisMaximum)).toEqual([1, 1, 5, 10, 10, 200000]);
  });

  it('keeps the latest day when all-time history spans more than a year', () => {
    const rows = [
      { dimensions: { created_day: '2023-01-01' }, metrics: { run_count: 4 } },
      { dimensions: { created_day: '2026-10-10' }, metrics: { run_count: 2 } },
    ];
    const series = dailySeries(rows, 'run_count', 'all', now);
    expect(series.length).toBeGreaterThan(1000);
    expect(series[0]).toEqual({ day: '2023-01-01', value: 4 });
    expect(series.at(-1)).toEqual({ day: '2026-10-10', value: 2 });
    expect(series.reduce((sum, day) => sum + day.value, 0)).toBe(6);
    expect(dashboardRequests('all', now).runsByDay.limit).toBeUndefined();
  });
});
