import { ApiError } from '../api/client';
import type { AgentRunState, SkillDefinition } from '../api';

export type RunSkillIssue = {
  reason: 'revision_changed' | 'disabled' | 'deleted' | 'revision_unavailable';
  names: string[];
};

export function skillErrorIssues(error: unknown, run: AgentRunState | null): RunSkillIssue[] {
  if (!(error instanceof ApiError)) return [];
  const reason =
    error.errorType === 'SkillDisabledError'
      ? 'disabled'
      : error.errorType === 'SkillNotFoundError'
        ? 'deleted'
        : error.errorType === 'SkillConflictError'
          ? 'revision_changed'
          : null;
  if (!reason) return [];
  let detail = error.detail;
  if (typeof detail === 'string') {
    try {
      detail = JSON.parse(detail);
    } catch {
      detail = null;
    }
  }
  const value = detail && typeof detail === 'object' ? (detail as Record<string, unknown>) : {};
  const names =
    Array.isArray(value.skill_names) && value.skill_names.every((name) => typeof name === 'string')
      ? (value.skill_names as string[])
      : (run?.request.skills || []).map((skill) => skill.skill_name);
  return [
    { reason: value.reason === 'revision_unavailable' ? 'revision_unavailable' : reason, names },
  ];
}

export function runFailureError(run: AgentRunState): ApiError | null {
  const failure = run.failure;
  const event = [...(run.trace || [])]
    .reverse()
    .find((event) => event.event_type === 'run_stopped' && event.error_type);
  const type = event?.error_type || failure?.error_type;
  if (typeof type !== 'string') return null;
  return new ApiError(event?.error_message || failure?.message || type, {
    status: type === 'SkillNotFoundError' ? 404 : 409,
    errorType: type,
    detail: event?.payload?.error_detail || failure?.detail,
    path: `/agent-runs/${run.run_id}`,
    requestId: null,
  });
}

export function runSkillIssues(
  run: AgentRunState | null,
  skills: SkillDefinition[] | null,
): RunSkillIssue[] {
  if (!run || !['paused', 'failed', 'running'].includes(run.status || '')) return [];
  const failure = skillErrorIssues(runFailureError(run), run);
  if (failure.length) return failure;
  const names = [...new Set((run.request.skills || []).map((skill) => skill.skill_name))];
  if (!names.length) return [];
  if (!run.skill_revisions || names.some((name) => !Object.hasOwn(run.skill_revisions!, name))) {
    if (run.status === 'running') return [];
    return [{ reason: 'revision_unavailable', names }];
  }
  if (skills === null) return [];
  return names.flatMap((name) => {
    const skill = skills.find((skill) => skill.name === name);
    const reason = !skill
      ? 'deleted'
      : skill.is_enabled === false
        ? 'disabled'
        : (skill.revision ?? null) !== run.skill_revisions![name]
          ? 'revision_changed'
          : null;
    return reason ? [{ reason, names: [name] }] : [];
  });
}

export function skillIssueText(issue: RunSkillIssue): string {
  const labels = {
    revision_changed: '版本已变更',
    disabled: '已停用',
    deleted: '已删除',
    revision_unavailable: '原运行未记录版本',
  };
  return `${issue.names.join('、') || '所选技能'}：${labels[issue.reason]}`;
}

export function canRetryRun(run: AgentRunState | null): boolean {
  return Boolean(
    run &&
    (['failed', 'canceled'].includes(run.status || '') ||
      (run.status === 'paused' && run.pause?.resumable === false)),
  );
}
