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
  // A finished call under a second reads as "0.0 秒" in seconds; show milliseconds instead.
  if (!activity.running && duration < 1000) {
    return duration < 1 ? null : `${Math.round(duration)} 毫秒`;
  }
  const seconds = duration / 1000;
  return seconds < 60
    ? `${seconds.toFixed(1)} 秒`
    : `${Math.floor(seconds / 60)} 分 ${Math.floor(seconds % 60)} 秒`;
}
