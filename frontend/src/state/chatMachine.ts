import { assign, createActor, fromPromise, setup } from 'xstate'
import type {
  AgentRunState,
  AgentTraceEvent,
  Session,
  ToolDefinition,
} from '../api'
import {
  applyChatTrace,
  completeStreamedResponse,
  userEntry,
  type ChatSubmission,
  type ChatTranscriptEntry,
} from '../domain/chat'
import {
  createChatContextId,
  createChatRunId,
  cancelChatRun,
  clearChatContext,
  createChatSession,
  deleteChatSession,
  prepareChatContext,
  loadChatSession,
  resumeChatRunStream,
  retryChatRun,
  streamChatRun,
  type ApprovalStatuses,
  type ChatCancelInput,
  type ChatClearInput,
  type ChatRequestInput,
  type ChatResumeInput,
  type ChatRetryInput,
  type ChatSessionInput,
  type ChatSessionSnapshot,
} from '../runtime/chatRuntime'

type ChatPendingRequest = {
  submission: ChatSubmission
  tools: ToolDefinition[]
}

export type ChatMachineContext = {
  transcript: ChatTranscriptEntry[]
  trace: AgentTraceEvent[]
  contextId: string | null
  runId: string | null
  contextReady: boolean
  pending: ChatPendingRequest | null
  run: AgentRunState | null
  session: Session | null
  requestedSession: Session | null
  sessionOperation: 'create' | 'load' | 'delete' | null
  deletedSessionId: string | null
  approvalStatuses: ApprovalStatuses
  error: unknown
}

export type ChatMachineEvent =
  | { type: 'SEND'; submission: ChatSubmission; tools: ToolDefinition[] }
  | { type: 'RETRY' }
  | { type: 'APPROVE'; approvalId: string }
  | { type: 'DENY'; approvalId: string }
  | { type: 'RESUME' }
  | { type: 'CREATE_SESSION'; session: Session }
  | { type: 'SELECT_SESSION'; session: Session }
  | { type: 'DELETE_SESSION'; sessionId: string }
  | { type: 'CANCEL' }
  | { type: 'TRACE'; event: AgentTraceEvent }
  | { type: 'CLEAR' }

export type {
  ChatCancelInput,
  ChatClearInput,
  ChatRequestInput,
  ChatResumeInput,
  ChatRetryInput,
}

const emptyContext = (): ChatMachineContext => ({
  transcript: [],
  trace: [],
  contextId: null,
  runId: null,
  contextReady: false,
  pending: null,
  run: null,
  session: null,
  requestedSession: null,
  sessionOperation: null,
  deletedSessionId: null,
  approvalStatuses: {},
  error: null,
})

const sessionLoadedContext = {
  transcript: ({ event }: { event: { output: ChatSessionSnapshot } }) => (
    event.output.transcript
  ),
  trace: [],
  contextId: ({ event }: { event: { output: ChatSessionSnapshot } }) => (
    event.output.session.context_id
  ),
  runId: null,
  contextReady: true,
  pending: null,
  run: null,
  session: ({ event }: { event: { output: ChatSessionSnapshot } }) => event.output.session,
  requestedSession: null,
  sessionOperation: null,
  deletedSessionId: null,
  approvalStatuses: {},
  error: null,
}

export const chatMachine = setup({
  types: {
    context: {} as ChatMachineContext,
    events: {} as ChatMachineEvent,
  },
  actors: {
    prepareContext: fromPromise<void, string>(({ input, signal }) => (
      prepareChatContext(input, signal)
    )),
    streamChat: fromPromise<AgentRunState, ChatRequestInput>(({ input, signal }) => (
      streamChatRun(input, signal)
    )),
    resumeChat: fromPromise<AgentRunState, ChatResumeInput & {
      onTrace?: (event: AgentTraceEvent) => void
    }>(({ input, signal }) => (
      resumeChatRunStream(input, signal)
    )),
    retryChat: fromPromise<AgentRunState, ChatRetryInput>(({ input, signal }) => (
      retryChatRun(input, signal)
    )),
    cancelChat: fromPromise<AgentRunState | null, ChatCancelInput>(({ input, signal }) => (
      cancelChatRun(input, signal)
    )),
    clearChat: fromPromise<void, ChatClearInput>(({ input, signal }) => (
      clearChatContext(input, signal)
    )),
    createSession: fromPromise<ChatSessionSnapshot, ChatSessionInput>(({ input, signal }) => (
      createChatSession(input, signal)
    )),
    deleteSession: fromPromise<string, ChatSessionInput>(({ input, signal }) => (
      deleteChatSession(input, signal)
    )),
    loadSession: fromPromise<ChatSessionSnapshot, ChatSessionInput>(({ input, signal }) => (
      loadChatSession(input, signal)
    )),
  },
}).createMachine({
  id: 'chat',
  initial: 'idle',
  context: emptyContext,
  on: {
    DELETE_SESSION: {
      guard: ({ context, event }) => context.session?.session_id === event.sessionId,
      target: '.deletingSession',
      actions: assign({ requestedSession: ({ context }) => context.session, sessionOperation: 'delete', error: null }),
    },
    CREATE_SESSION: {
      target: '.creatingSession',
      actions: assign({
        requestedSession: ({ event }) => event.session,
        sessionOperation: 'create',
        error: null,
      }),
    },
    SELECT_SESSION: {
      target: '.loadingSession',
      actions: assign({
        requestedSession: ({ event }) => event.session,
        sessionOperation: 'load',
        error: null,
      }),
    },
  },
  states: {
    deletingSession: {
      invoke: {
        src: 'deleteSession',
        input: ({ context }) => sessionInput(context),
        onDone: {
          target: 'idle',
          actions: assign(({ event }) => ({ ...emptyContext(), deletedSessionId: event.output })),
        },
        onError: { target: 'failed', actions: assign({ error: ({ event }) => event.error }) },
      },
    },
    creatingSession: {
      invoke: {
        id: 'createSession',
        src: 'createSession',
        input: ({ context }) => sessionInput(context),
        onDone: {
          target: 'idle',
          actions: assign(sessionLoadedContext),
        },
        onError: {
          target: 'failed',
          actions: assign({ error: ({ event }) => event.error }),
        },
      },
    },
    loadingSession: {
      invoke: {
        id: 'loadSession',
        src: 'loadSession',
        input: ({ context }) => sessionInput(context),
        onDone: {
          target: 'idle',
          actions: assign(sessionLoadedContext),
        },
        onError: {
          target: 'failed',
          actions: assign({ error: ({ event }) => event.error }),
        },
      },
    },
    idle: {
      on: {
        SEND: {
          target: 'preparing',
          actions: assign({
            contextId: ({ context }) => context.contextId || createChatContextId(),
            runId: () => createChatRunId(),
            pending: ({ event }) => ({
              submission: event.submission,
              tools: event.tools,
            }),
            transcript: ({ context, event }) => [
              ...context.transcript,
              userEntry(event.submission, context.transcript.length + 1),
            ],
            trace: [],
            run: null,
            approvalStatuses: {},
            error: null,
          }),
        },
        CLEAR: {
          target: 'clearing',
        },
      },
    },
    preparing: {
      always: {
        guard: ({ context }) => context.contextReady,
        target: 'streaming',
      },
      invoke: {
        id: 'prepareContext',
        src: 'prepareContext',
        input: ({ context }) => context.contextId as string,
        onDone: {
          target: 'streaming',
          actions: assign({
            contextReady: true,
            error: null,
          }),
        },
        onError: {
          target: 'failed',
          actions: assign({
            error: ({ event }) => event.error,
          }),
        },
      },
      on: {
        CANCEL: [
          {
            guard: ({ context }) => context.contextReady,
            target: 'canceling',
          },
          'canceled',
        ],
        CLEAR: [
          {
            guard: ({ context }) => context.contextReady,
            target: 'clearing',
          },
          {
            target: 'canceled',
            actions: assign(emptyContext),
          },
        ],
      },
    },
    streaming: {
      invoke: {
        id: 'streamChat',
        src: 'streamChat',
        input: ({ context, self }) => ({
          contextId: context.contextId as string,
          sessionId: context.session?.session_id,
          runId: context.runId as string,
          submission: (context.pending as ChatPendingRequest).submission,
          tools: (context.pending as ChatPendingRequest).tools,
          onTrace: (event: AgentTraceEvent) => self.send({ type: 'TRACE', event }),
        }),
        onDone: {
          target: 'evaluatingRun',
          actions: assign({
            run: ({ event }) => event.output,
            runId: ({ event }) => event.output.run_id,
            approvalStatuses: {},
            error: null,
          }),
        },
        onError: {
          target: 'failed',
          actions: assign({
            error: ({ event }) => event.error,
          }),
        },
      },
      on: {
        TRACE: {
          actions: assign({
            trace: ({ context, event }) => [...context.trace, event.event],
            transcript: ({ context, event }) => applyChatTrace(context.transcript, event.event, context.runId || ''),
          }),
        },
        CANCEL: 'canceling',
        CLEAR: 'clearing',
      },
    },
    approvalRequired: {
      entry: assign({ transcript: ({ context }) => context.transcript.map((entry) => ({ ...entry, streaming: false })) }),
      on: {
        APPROVE: [
          {
            guard: ({ context, event }) => completesApprovals(context, event),
            target: 'resuming',
            actions: assign({
              approvalStatuses: ({ context, event }) => recordApproval(context, event),
            }),
          },
          {
            guard: ({ context, event }) => isPendingApproval(context, event.approvalId),
            actions: assign({
              approvalStatuses: ({ context, event }) => recordApproval(context, event),
            }),
          },
        ],
        DENY: [
          {
            guard: ({ context, event }) => completesApprovals(context, event),
            target: 'resuming',
            actions: assign({
              approvalStatuses: ({ context, event }) => recordApproval(context, event),
            }),
          },
          {
            guard: ({ context, event }) => isPendingApproval(context, event.approvalId),
            actions: assign({
              approvalStatuses: ({ context, event }) => recordApproval(context, event),
            }),
          },
        ],
        CANCEL: 'canceling',
        CLEAR: {
          target: 'clearing',
        },
      },
    },
    resumeRequired: {
      entry: assign({ transcript: ({ context }) => context.transcript.map((entry) => ({ ...entry, streaming: false })) }),
      on: {
        RESUME: {
          target: 'resuming',
          actions: assign({ approvalStatuses: {} }),
        },
        CANCEL: 'canceling',
        CLEAR: 'clearing',
      },
    },
    resuming: {
      invoke: {
        id: 'resumeChat',
        src: 'resumeChat',
        input: ({ context, self }) => ({
          run: context.run as AgentRunState,
          approvalStatuses: context.approvalStatuses,
          onTrace: (event: AgentTraceEvent) => self.send({ type: 'TRACE', event }),
        }),
        onDone: {
          target: 'evaluatingRun',
          actions: assign({
            run: ({ event }) => event.output,
            approvalStatuses: {},
            error: null,
          }),
        },
        onError: {
          target: 'failed',
          actions: assign({
            error: ({ event }) => event.error,
          }),
        },
      },
      on: {
        TRACE: {
          actions: assign({
            trace: ({ context, event }) => [...context.trace, event.event],
            transcript: ({ context, event }) => applyChatTrace(context.transcript, event.event, context.runId || ''),
          }),
        },
        CANCEL: 'canceling',
        CLEAR: 'clearing',
      },
    },
    retrying: {
      invoke: {
        id: 'retryChat',
        src: 'retryChat',
        input: ({ context, self }) => ({
          run: context.run as AgentRunState,
          runId: context.runId as string,
          onTrace: (event: AgentTraceEvent) => self.send({ type: 'TRACE', event }),
        }),
        onDone: {
          target: 'evaluatingRun',
          actions: assign({
            run: ({ event }) => event.output,
            runId: ({ event }) => event.output.run_id,
            approvalStatuses: {},
            error: null,
          }),
        },
        onError: {
          target: 'failed',
          actions: assign({
            error: ({ event }) => event.error,
          }),
        },
      },
      on: {
        TRACE: {
          actions: assign({
            trace: ({ context, event }) => [...context.trace, event.event],
            transcript: ({ context, event }) => applyChatTrace(context.transcript, event.event, context.runId || ''),
          }),
        },
        CANCEL: 'canceling',
        CLEAR: 'clearing',
      },
    },
    canceling: {
      entry: assign({ transcript: ({ context }) => context.transcript.map((entry) => ({ ...entry, streaming: false })) }),
      invoke: {
        id: 'cancelChat',
        src: 'cancelChat',
        input: ({ context }) => ({
          run: context.run,
          runId: context.runId,
        }),
        onDone: {
          target: 'canceled',
          actions: assign({
            run: ({ event }) => event.output,
            approvalStatuses: {},
            error: null,
          }),
        },
        onError: {
          target: 'canceled',
          actions: assign({
            error: ({ event }) => event.error,
          }),
        },
      },
      on: {
        CLEAR: 'clearing',
      },
    },
    clearing: {
      invoke: {
        id: 'clearChat',
        src: 'clearChat',
        input: ({ context }) => ({
          contextId: context.contextId,
          sessionId: context.session?.session_id,
          run: context.run,
          runId: context.runId,
        }),
        onDone: [
          {
            guard: ({ context }) => context.session !== null,
            target: 'idle',
            actions: assign({
              transcript: [],
              trace: [],
              runId: null,
              pending: null,
              run: null,
              approvalStatuses: {},
              error: null,
            }),
          },
          {
            target: 'canceled',
            actions: assign(emptyContext),
          },
        ],
        onError: {
          target: 'idle',
          actions: assign({
            error: ({ event }) => event.error,
          }),
        },
      },
    },
    canceled: {
      on: {
        SEND: {
          target: 'preparing',
          actions: assign({
            contextId: ({ context }) => context.contextId || createChatContextId(),
            runId: () => createChatRunId(),
            pending: ({ event }) => ({
              submission: event.submission,
              tools: event.tools,
            }),
            transcript: ({ context, event }) => [
              ...context.transcript,
              userEntry(event.submission, context.transcript.length + 1),
            ],
            trace: [],
            run: null,
            approvalStatuses: {},
            error: null,
          }),
        },
        CLEAR: {
          target: 'clearing',
        },
      },
    },
    evaluatingRun: {
      always: [
        {
          guard: ({ context }) => isApprovalPause(context.run),
          target: 'approvalRequired',
        },
        {
          guard: ({ context }) => isManualPause(context.run),
          target: 'resumeRequired',
        },
        {
          guard: ({ context }) => context.run?.status === 'paused',
          target: 'retrying',
          actions: assign({
            runId: () => createChatRunId(),
            trace: [],
          }),
        },
        {
          guard: ({ context }) => isSuccessfullyFinishedRun(context.run),
          target: 'idle',
          actions: assign({
            transcript: ({ context }) => completeStreamedResponse(
              context.transcript, context.run!.response!, context.runId || '',
            ),
            pending: null,
            approvalStatuses: {},
            error: null,
          }),
        },
        {
          target: 'failed',
          actions: assign({
            approvalStatuses: {},
            error: ({ context }) => agentRunError(context.run as AgentRunState),
          }),
        },
      ],
    },
    failed: {
      entry: assign({ transcript: ({ context }) => context.transcript.map((entry) => ({ ...entry, streaming: false })) }),
      on: {
        CANCEL: [
          {
            guard: ({ context }) => hasPotentiallyActiveRun(context),
            target: 'canceling',
          },
          { target: 'canceled' },
        ],
        RETRY: [
          { guard: ({ context }) => context.sessionOperation === 'delete', target: 'deletingSession' },
          {
            guard: ({ context }) => context.sessionOperation === 'create',
            target: 'creatingSession',
          },
          {
            guard: ({ context }) => context.sessionOperation === 'load',
            target: 'loadingSession',
          },
          {
            guard: ({ context }) => (
              isApprovalPause(context.run) || isManualPause(context.run)
            ),
            target: 'resuming',
          },
          {
            guard: ({ context }) => context.run !== null,
            target: 'retrying',
            actions: assign({
              runId: () => createChatRunId(),
              trace: [],
            }),
          },
          {
            guard: ({ context }) => !context.contextReady,
            target: 'preparing',
          },
          { target: 'streaming' },
        ],
        SEND: {
          guard: ({ context }) => !hasPotentiallyActiveRun(context),
          target: 'preparing',
          actions: assign({
            runId: () => createChatRunId(),
            pending: ({ event }) => ({
              submission: event.submission,
              tools: event.tools,
            }),
            transcript: ({ context, event }) => [
              ...context.transcript,
              userEntry(event.submission, context.transcript.length + 1),
            ],
            trace: [],
            run: null,
            sessionOperation: null,
            requestedSession: null,
            approvalStatuses: {},
            error: null,
          }),
        },
        CLEAR: {
          target: 'clearing',
        },
      },
    },
  },
})

export const chatActor = createActor(chatMachine)

function agentRunError(run: AgentRunState): Error {
  if (run.stop_reason === 'tool_rounds_exhausted') {
    return new Error(
      `Agent run exhausted ${run.tool_rounds_used ?? 'all'} tool rounds before finishing`,
    )
  }
  const detail = run.stop_reason || run.status || 'unknown state'
  return new Error(`Agent run did not finish: ${detail}`)
}

function isSuccessfullyFinishedRun(run: AgentRunState | null): boolean {
  return run?.status === 'finished'
    && run.response != null
    && (run.stop_reason == null || run.stop_reason === 'finished')
}

function isRecoverablePause(run: AgentRunState | null): boolean {
  if (run?.status !== 'paused') {
    return false
  }
  const runtime = run.metadata?.agent_runtime
  return !(runtime && typeof runtime === 'object'
    && 'recovery_eligible' in runtime
    && runtime.recovery_eligible === false)
}

function isApprovalPause(run: AgentRunState | null): boolean {
  return isRecoverablePause(run) && (run?.pending_approval_requests?.length || 0) > 0
}

function isManualPause(run: AgentRunState | null): boolean {
  if (!isRecoverablePause(run)) {
    return false
  }
  const runtime = run?.metadata?.agent_runtime
  return Boolean(runtime && typeof runtime === 'object'
    && 'manual_pause' in runtime
    && runtime.manual_pause === true)
}

type ApprovalDecisionEvent = Extract<
  ChatMachineEvent,
  { type: 'APPROVE' | 'DENY' }
>

function isPendingApproval(context: ChatMachineContext, approvalId: string): boolean {
  return Boolean(context.run?.pending_approval_requests?.some(
    (request) => request.approval_id === approvalId,
  ))
}

function recordApproval(
  context: ChatMachineContext,
  event: ApprovalDecisionEvent,
): ApprovalStatuses {
  return {
    ...context.approvalStatuses,
    [event.approvalId]: event.type === 'APPROVE' ? 'approved' : 'denied',
  }
}

function completesApprovals(
  context: ChatMachineContext,
  event: ApprovalDecisionEvent,
): boolean {
  if (!isPendingApproval(context, event.approvalId)) {
    return false
  }
  const statuses = recordApproval(context, event)
  return Boolean(context.run?.pending_approval_requests?.every(
    (request) => statuses[request.approval_id],
  ))
}

function hasPotentiallyActiveRun(context: ChatMachineContext): boolean {
  if (!context.runId) {
    return false
  }
  return !context.run
    || context.run.run_id !== context.runId
    || context.run.status === 'running'
    || context.run.status === 'paused'
}

function sessionInput(context: ChatMachineContext): ChatSessionInput {
  return {
    session: context.requestedSession as Session,
    currentRun: context.run,
    currentRunId: context.runId,
  }
}
