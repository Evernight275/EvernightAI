import { waitFor } from 'xstate'
import { createChatSessionDraft } from './chatSidebar'
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import { getAgentRun, getContext, getSession, type AgentRunRequest, type AgentRunState } from '../../api'
import type { ChatSubmission } from '../../domain/chat'
import { chatActor } from '../../state/chatMachine'
import { workspaceActor } from '../../state/workspaceMachine'
import { prerequisiteNotice } from './chatPrerequisites'
import { runSkillIssues, skillErrorIssues } from '../../domain/runSkills'
import { reconcileRunTranscript, transcriptFromMessages } from '../../domain/chat'
import { cancelForEditing, readRunDecisions, saveRunDecisions } from '../../runtime/runEditor'
import { authGeneration } from '../../runtime/workspaceRuntime'

export function useChatView() {
  const workspaceSnapshot = shallowRef(workspaceActor.getSnapshot())
  const chatSnapshot = shallowRef(chatActor.getSnapshot())
  const detailsOpen = ref(false)
  const lifetime = new AbortController()
  const editing = ref(false)
  const restoring = ref(false)
  const editorError = shallowRef<unknown>(null)
  const editRequest = shallowRef<{ id: string; request: AgentRunRequest } | null>(null)
  let operation = 0
  let operationController = new AbortController()
  function stopOperation() {
    operation++; operationController.abort(); operationController = new AbortController()
    restoring.value = false; editing.value = false
  }

  const workspaceSubscription = workspaceActor.subscribe((snapshot) => {
    workspaceSnapshot.value = snapshot
  })
  const chatSubscription = chatActor.subscribe((snapshot) => {
    chatSnapshot.value = snapshot
  })
  watch(() => workspaceSnapshot.value.context.workspace, workspace => {
    chatActor.send({ type: 'SKILL_CATALOG', skills: workspace.loadedAt
      && !workspaceSnapshot.value.context.issues.some(issue => issue.resource === 'skills')
      ? workspace.capabilityCatalog.skills : null })
  }, { immediate: true })
  watch(() => chatSnapshot.value.context.runId, id => {
    if (restoring.value) return
    stopOperation(); editRequest.value = null; editorError.value = null
    const url = new URL(window.location.href)
    if (id) url.searchParams.set('run', id)
    else url.searchParams.delete('run')
    url.searchParams.delete('edit')
    window.history.replaceState(null, '', url)
  }, { flush: 'sync' })
  watch(() => [chatSnapshot.value.context.run, chatSnapshot.value.context.approvalStatuses] as const, ([run, choices]) => {
    if (run) saveRunDecisions(run, choices)
  }, { flush: 'sync' })
  watch(authGeneration, () => {
    stopOperation(); editRequest.value = null; editorError.value = null
  }, { flush: 'sync' })
  watch(() => chatSnapshot.value.context.requestedSession, session => {
    if (session) { stopOperation(); editRequest.value = null; editorError.value = null }
  }, { flush: 'sync' })
  onMounted(async () => {
    const url = new URL(window.location.href)
    const id = url.searchParams.get('run')
    if (!id || chatActor.getSnapshot().context.runId) return
    const current = ++operation
    const generation = authGeneration.value
    const signal = AbortSignal.any([lifetime.signal, operationController.signal])
    restoring.value = true
    try {
      const run = await getAgentRun(id, signal)
      signal.throwIfAborted()
      const context = await getContext(run.request.context_id, signal)
      signal.throwIfAborted()
      const sessionId = run.request.metadata?.session_id
      const session = typeof sessionId === 'string' ? await getSession(sessionId, signal) : null
      if (lifetime.signal.aborted || current !== operation || generation !== authGeneration.value
        || chatActor.getSnapshot().context.runId || chatActor.getSnapshot().context.session
        || chatActor.getSnapshot().context.sessionOperation) return
      chatActor.send({ type: 'OPEN_RUN', run, session,
        transcript: reconcileRunTranscript(transcriptFromMessages([
          ...context.messages || [], ...(run.status === 'finished' ? [] : run.request.messages || []),
        ]), run), choices: readRunDecisions(run) })
      if (url.searchParams.get('edit') === '1' && ['canceled', 'failed'].includes(run.status || ''))
        editRequest.value = { id: run.run_id, request: run.request }
      url.searchParams.delete('edit'); window.history.replaceState(null, '', url)
    } catch (cause) { if (current === operation && !lifetime.signal.aborted) editorError.value = cause }
    finally { if (current === operation) restoring.value = false }
  })
  const skillIssues = computed(() => {
    const context = chatSnapshot.value.context
    if (context.skillIssues.length) return context.skillIssues
    const errors = skillErrorIssues(context.error, context.run)
    return errors.length ? errors : runSkillIssues(context.run, context.skills)
  })

  onUnmounted(() => {
    lifetime.abort()
    workspaceSubscription.unsubscribe()
    chatSubscription.unsubscribe()
  })

  return {
    skills: computed(() => workspaceSnapshot.value.context.workspace.capabilityCatalog.skills),
    workspaceState: computed(() => String(workspaceSnapshot.value.value)),
    chatState: computed(() => String(chatSnapshot.value.value)),
    detailsOpen,
    authGeneration,
    editRequest, editing, skillIssues,
    contextId: computed(() => chatSnapshot.value.context.contextId),
    async editRun(): Promise<void> {
      const snapshot = chatActor.getSnapshot()
      if (!snapshot.context.runId || editing.value) return
      const current = ++operation
      const signal = AbortSignal.any([lifetime.signal, operationController.signal])
      editing.value = true; editorError.value = null
      try {
        const run = await cancelForEditing(snapshot.context.runId, signal)
        if (current !== operation || lifetime.signal.aborted) return
        chatActor.send({ type: 'OPEN_RUN', run, session: snapshot.context.session,
          transcript: reconcileRunTranscript(snapshot.context.transcript, run), choices: {} })
        editRequest.value = { id: `${run.run_id}-${Date.now()}`, request: run.request }
      } catch (cause) { if (current === operation && !lifetime.signal.aborted) editorError.value = cause }
      finally { if (current === operation) editing.value = false }
    },
    openDetails(): void {
      detailsOpen.value = true
    },
    closeDetails(): void {
      detailsOpen.value = false
    },
    workspaceNotice: computed(() =>
      prerequisiteNotice(
        String(workspaceSnapshot.value.value),
        workspaceSnapshot.value.context.workspace.providerCatalog.providers.filter((provider) => provider.is_enabled !== false).length,
      ),
    ),
    workspaceIssues: computed(() => workspaceSnapshot.value.context.issues),
    providerCatalog: computed(() => workspaceSnapshot.value.context.workspace.providerCatalog),
    toolCatalog: computed(() => workspaceSnapshot.value.context.workspace.capabilityCatalog.tools),
    busy: computed(() => restoring.value || editing.value ||
      isChatSubmissionBlocked(
        String(chatSnapshot.value.value),
        chatSnapshot.value.context.run,
        chatSnapshot.value.context.runId,
      ),
    ),
    connection: computed(() => chatSnapshot.value.context.connection),
    error: computed(() => editorError.value || chatSnapshot.value.context.error),
    transcript: computed(() => chatSnapshot.value.context.transcript),
    hasTranscript: computed(() => chatSnapshot.value.context.transcript.length > 0),
    run: computed(() => chatSnapshot.value.context.run),
    session: computed(() => chatSnapshot.value.context.session),
    trace: computed(() => chatSnapshot.value.context.trace),
    runId: computed(() => chatSnapshot.value.context.runId),
    pendingApprovals: computed(() =>
      chatSnapshot.value.context.run?.run_id === chatSnapshot.value.context.runId
        ? chatSnapshot.value.context.run?.pending_approval_requests || []
        : [],
    ),
    approvalStatuses: computed(() => chatSnapshot.value.context.approvalStatuses),
    cancelableRun: computed(() =>
      isChatRunCancelable(
        String(chatSnapshot.value.value),
        chatSnapshot.value.context.run,
        chatSnapshot.value.context.runId,
      ),
    ),
    async send(submission: ChatSubmission): Promise<void> {
      if (!chatActor.getSnapshot().context.session && !chatActor.getSnapshot().context.contextReady) {
        const session = createChatSessionDraft(
          workspaceSnapshot.value.context.workspace.providerCatalog,
        )
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
        if (
          !snapshot.matches('idle') ||
          snapshot.context.session?.session_id !== session.session_id
        )
          return
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
  return (
    [
      'preparing',
      'streaming',
      'approvalRequired',
      'resumeRequired',
      'resuming',
      'retrying',
      'recovering',
    ].includes(state) ||
    (state === 'failed' && hasPotentiallyActiveRun(run, runId))
  )
}

function hasPotentiallyActiveRun(run: AgentRunState | null, runId: string | null): boolean {
  if (!runId) {
    return false
  }
  return !run || run.run_id !== runId || run.status === 'running' || run.status === 'paused'
}
