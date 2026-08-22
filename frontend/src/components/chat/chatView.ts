import { computed, onUnmounted, shallowRef } from 'vue'
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
    workspaceIssues: computed(() => workspaceSnapshot.value.context.issues),
    providerCatalog: computed(
      () => workspaceSnapshot.value.context.workspace.providerCatalog,
    ),
    toolCatalog: computed(
      () => workspaceSnapshot.value.context.workspace.capabilityCatalog.tools,
    ),
    busy: computed(() => ['preparing', 'sending', 'resuming', 'retrying'].includes(
      String(chatSnapshot.value.value),
    )),
    error: computed(() => chatSnapshot.value.context.error),
    transcript: computed(() => chatSnapshot.value.context.transcript),
    hasTranscript: computed(() => chatSnapshot.value.context.transcript.length > 0),
    run: computed(() => chatSnapshot.value.context.run),
    runId: computed(() => chatSnapshot.value.context.run?.run_id || null),
    pendingApprovals: computed(
      () => chatSnapshot.value.context.run?.pending_approval_requests || [],
    ),
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
    approve(): void {
      chatActor.send({ type: 'APPROVE' })
    },
    deny(): void {
      chatActor.send({ type: 'DENY' })
    },
  }
}
