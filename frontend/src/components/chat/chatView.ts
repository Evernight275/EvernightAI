import { computed, onUnmounted, shallowRef } from 'vue'
import type { AgentRunState } from '../../api'
import type { ChatSubmission } from '../../domain/chat'
import { chatActor } from '../../state/chatMachine'
import { workspaceActor } from '../../state/workspaceMachine'

export function useChatView() {
  const workspaceSnapshot = shallowRef(workspaceActor.getSnapshot())
  const chatSnapshot = shallowRef(chatActor.getSnapshot())

  const workspaceSubscription = workspaceActor.subscribe((snapshot) => {
    workspaceSnapshot.value = snapshot
  })
  const chatSubscription = chatActor.subscribe((snapshot) => {
    chatSnapshot.value = snapshot
  })

  onUnmounted(() => {
    workspaceSubscription.unsubscribe()
    chatSubscription.unsubscribe()
  })

  return {
    workspaceState: computed(() => String(workspaceSnapshot.value.value)),
    chatState: computed(() => String(chatSnapshot.value.value)),
    detailsOpen: computed(() => shouldOpenChatDetails(
      String(workspaceSnapshot.value.value),
      String(chatSnapshot.value.value),
      chatSnapshot.value.context.error,
      workspaceSnapshot.value.context.issues.length,
    )),
    workspaceIssues: computed(() => workspaceSnapshot.value.context.issues),
    providerCatalog: computed(
      () => workspaceSnapshot.value.context.workspace.providerCatalog,
    ),
    toolCatalog: computed(
      () => workspaceSnapshot.value.context.workspace.capabilityCatalog.tools,
    ),
    busy: computed(() => isChatSubmissionBlocked(
      String(chatSnapshot.value.value),
      chatSnapshot.value.context.run,
      chatSnapshot.value.context.runId,
    )),
    error: computed(() => chatSnapshot.value.context.error),
    transcript: computed(() => chatSnapshot.value.context.transcript),
    hasTranscript: computed(() => chatSnapshot.value.context.transcript.length > 0),
    run: computed(() => chatSnapshot.value.context.run),
    session: computed(() => chatSnapshot.value.context.session),
    trace: computed(() => chatSnapshot.value.context.trace),
    runId: computed(() => chatSnapshot.value.context.runId),
    pendingApprovals: computed(
      () => chatSnapshot.value.context.run?.pending_approval_requests || [],
    ),
    approvalStatuses: computed(() => chatSnapshot.value.context.approvalStatuses),
    cancelableRun: computed(() => isChatRunCancelable(
      String(chatSnapshot.value.value),
      chatSnapshot.value.context.run,
      chatSnapshot.value.context.runId,
    )),
    send(submission: ChatSubmission): void {
      chatActor.send({
        type: 'SEND',
        submission,
        tools: workspaceSnapshot.value.context.workspace.capabilityCatalog.tools,
      })
    },
    retry(): void {
      chatActor.send({ type: 'RETRY' })
    },
    clear(): void {
      chatActor.send({ type: 'CLEAR' })
    },
    cancel(): void {
      chatActor.send({ type: 'CANCEL' })
    },
    approve(approvalId: string): void {
      chatActor.send({ type: 'APPROVE', approvalId })
    },
    deny(approvalId: string): void {
      chatActor.send({ type: 'DENY', approvalId })
    },
    resume(): void {
      chatActor.send({ type: 'RESUME' })
    },
  }
}

export function shouldOpenChatDetails(
  workspaceState: string,
  chatState: string,
  error: unknown,
  issueCount: number,
): boolean {
  return issueCount > 0
    || Boolean(error)
    || workspaceState !== 'ready'
    || !['idle', 'canceled'].includes(chatState)
}

export function isChatSubmissionBlocked(
  state: string,
  run: AgentRunState | null,
  runId: string | null = run?.run_id || null,
): boolean {
  if (state === 'failed') {
    return hasPotentiallyActiveRun(run, runId)
  }
  return state !== 'idle' && state !== 'canceled'
}

export function isChatRunCancelable(
  state: string,
  run: AgentRunState | null,
  runId: string | null,
): boolean {
  return state === 'failed' && hasPotentiallyActiveRun(run, runId)
}

function hasPotentiallyActiveRun(
  run: AgentRunState | null,
  runId: string | null,
): boolean {
  if (!runId) {
    return false
  }
  return !run
    || run.run_id !== runId
    || run.status === 'running'
    || run.status === 'paused'
}
