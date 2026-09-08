import { waitFor } from 'xstate'
import { createChatSessionDraft } from './chatSidebar'
import { computed, onUnmounted, ref, shallowRef } from 'vue'
import type { AgentRunState } from '../../api'
import type { ChatSubmission } from '../../domain/chat'
import { chatActor } from '../../state/chatMachine'
import { workspaceActor } from '../../state/workspaceMachine'
import { prerequisiteNotice } from './chatPrerequisites'

export function useChatView() {
  const workspaceSnapshot = shallowRef(workspaceActor.getSnapshot())
  const chatSnapshot = shallowRef(chatActor.getSnapshot())
  const detailsOpen = ref(false)
  const lifetime = new AbortController()

  const workspaceSubscription = workspaceActor.subscribe((snapshot) => {
    workspaceSnapshot.value = snapshot
  })
  const chatSubscription = chatActor.subscribe((snapshot) => {
    chatSnapshot.value = snapshot
  })

  onUnmounted(() => {
    lifetime.abort()
    workspaceSubscription.unsubscribe()
    chatSubscription.unsubscribe()
  })

  return {
    workspaceState: computed(() => String(workspaceSnapshot.value.value)),
    chatState: computed(() => String(chatSnapshot.value.value)),
    detailsOpen,
    openDetails(): void { detailsOpen.value = true },
    closeDetails(): void { detailsOpen.value = false },
    workspaceNotice: computed(() => prerequisiteNotice(
      String(workspaceSnapshot.value.value),
      workspaceSnapshot.value.context.workspace.providerCatalog.providers.length,
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
    async send(submission: ChatSubmission): Promise<void> {
      if (!chatActor.getSnapshot().context.session) {
        const session = createChatSessionDraft(workspaceSnapshot.value.context.workspace.providerCatalog)
        session.provider_id = submission.providerId
        session.model_id = submission.modelId
        chatActor.send({ type: 'CREATE_SESSION', session })
        try {
          await waitFor(chatActor, (snapshot) => !snapshot.matches('creatingSession'), {
            signal: lifetime.signal,
          })
        } catch {
          return
        }
        const snapshot = chatActor.getSnapshot()
        if (!snapshot.matches('idle') || snapshot.context.session?.session_id !== session.session_id) return
      }
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
  return ['preparing', 'streaming', 'approvalRequired', 'resumeRequired',
    'resuming', 'retrying'].includes(state)
    || (state === 'failed' && hasPotentiallyActiveRun(run, runId))
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
