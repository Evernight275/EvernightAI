export function toolElapsed(
  activity: { startedAt?: string; finishedAt?: string; durationMs?: number; running?: boolean },
  now = Date.now(),
): string | null {
  let duration = activity.durationMs;
  if (duration === undefined && activity.startedAt && (activity.finishedAt || activity.running)) {
    duration =
      (activity.finishedAt ? Date.parse(activity.finishedAt) : now) -
      Date.parse(activity.startedAt);
  }
  if (duration === undefined || !Number.isFinite(duration) || duration < 0) return null;
  const seconds = duration / 1000;
  return seconds < 60
    ? `${seconds.toFixed(1)} 秒`
    : `${Math.floor(seconds / 60)} 分 ${Math.floor(seconds % 60)} 秒`;
}
