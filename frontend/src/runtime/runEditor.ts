import { cancelAgentRun, getAgentRun, type AgentRunRequest, type AgentRunState } from '../api'
import type { ApprovalStatuses } from './chatRuntime'

const prefix = 'evernight.runDecisions.'

export function readRunDecisions(run: AgentRunState): ApprovalStatuses {
  if (typeof sessionStorage === 'undefined') return {}
  try {
    const saved = JSON.parse(sessionStorage.getItem(prefix + run.run_id) || '{}') as Record<string, unknown>
    return Object.fromEntries((run.pending_approval_requests || []).flatMap(item =>
      saved[item.approval_id] === 'approved' || saved[item.approval_id] === 'denied'
        ? [[item.approval_id, saved[item.approval_id]]] : [],
    )) as ApprovalStatuses
  } catch { return {} }
}

export function saveRunDecisions(run: AgentRunState, choices: ApprovalStatuses): void {
  if (typeof sessionStorage === 'undefined') return
  try {
    if (run.status !== 'paused' || !Object.keys(choices).length) sessionStorage.removeItem(prefix + run.run_id)
    else sessionStorage.setItem(prefix + run.run_id, JSON.stringify(choices))
  } catch { /* Storage can be unavailable in private browsing. */ }
}

export function clearRunEditorStorage(): void {
  if (typeof sessionStorage === 'undefined') return
  try {
    for (const key of Object.keys(sessionStorage))
      if (key.startsWith(prefix) || key.startsWith('evernight.chatDraft.')) sessionStorage.removeItem(key)
  } catch { /* Identity changes must still complete without storage. */ }
}

export async function cancelForEditing(runId: string, signal?: AbortSignal): Promise<AgentRunState> {
  let run = await getAgentRun(runId, signal)
  signal?.throwIfAborted()
  if (run.status === 'running' || run.status === 'paused')
    run = await cancelAgentRun(runId, { reason: 'edit request after skill conflict' }, signal)
  if (!['canceled', 'failed'].includes(run.status || '')) throw new Error('运行尚未取消，请刷新状态后重试')
  saveRunDecisions(run, {})
  return run
}

export function editableRunOptions(request: Partial<AgentRunRequest>): Partial<AgentRunRequest> {
  const metadata = { ...request.metadata }
  for (const key of ['run_id', 'retry_of', 'retry_attempt', 'retried_run_id', 'agent_runtime', 'agent_run', 'session_id']) delete metadata[key]
  return {
    tools: request.tools, memory_query: request.memory_query, max_tool_rounds: request.max_tool_rounds,
    recover_tool_errors: request.recover_tool_errors, write_memory: request.write_memory, metadata,
  }
}
