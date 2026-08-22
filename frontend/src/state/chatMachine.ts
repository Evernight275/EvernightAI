import { assign, createActor, fromPromise, setup } from 'xstate'
import type {
  AgentRunState,
  AgentTraceEvent,
  ToolApprovalStatus,
  ToolDefinition,
} from '../api'
import {
  assistantEntry,
  userEntry,
  type ChatSubmission,
  type ChatTranscriptEntry,
} from '../domain/chat'
import {
  createChatContextId,
  createChatRunId,
  cancelChatRun,
  clearChatContext,
  prepareChatContext,
  resumeChatRunStream,
  retryChatRun,
  streamChatRun,
  type ChatCancelInput,
  type ChatClearInput,
  type ChatRequestInput,
  type ChatResumeInput,
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
  approvalStatus: Extract<ToolApprovalStatus, 'approved' | 'denied'> | null
  error: unknown
}

export type ChatMachineEvent =
  | { type: 'SEND'; submission: ChatSubmission; tools: ToolDefinition[] }
  | { type: 'RETRY' }
  | { type: 'APPROVE' }
  | { type: 'DENY' }
  | { type: 'CANCEL' }
  | { type: 'TRACE'; event: AgentTraceEvent }
  | { type: 'CLEAR' }

export type { ChatCancelInput, ChatClearInput, ChatRequestInput, ChatResumeInput }

const emptyContext = (): ChatMachineContext => ({
  transcript: [],
  trace: [],
  contextId: null,
  runId: null,
  contextReady: false,
  pending: null,
  run: null,
  approvalStatus: null,
  error: null,
})

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
      resumeChatRunStream(input, signal, input.onTrace)
    )),
    retryChat: fromPromise<AgentRunState, AgentRunState>(({ input, signal }) => (
      retryChatRun(input, signal)
    )),
    cancelChat: fromPromise<AgentRunState | null, ChatCancelInput>(({ input, signal }) => (
      cancelChatRun(input, signal)
    )),
    clearChat: fromPromise<void, ChatClearInput>(({ input, signal }) => (
      clearChatContext(input, signal)
    )),
  },
}).createMachine({
  id: 'chat',
  initial: 'idle',
  context: emptyContext,
  states: {
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
            approvalStatus: null,
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
            approvalStatus: null,
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
          }),
        },
        CANCEL: 'canceling',
        CLEAR: 'clearing',
      },
    },
    approvalRequired: {
      on: {
        APPROVE: {
          target: 'resuming',
          actions: assign({ approvalStatus: 'approved' }),
        },
        DENY: {
          target: 'resuming',
          actions: assign({ approvalStatus: 'denied' }),
        },
        CANCEL: 'canceling',
        CLEAR: {
          target: 'clearing',
        },
      },
    },
    resuming: {
      invoke: {
        id: 'resumeChat',
        src: 'resumeChat',
        input: ({ context, self }) => ({
          run: context.run as AgentRunState,
          status: context.approvalStatus as Extract<
            ToolApprovalStatus,
            'approved' | 'denied'
          >,
          onTrace: (event: AgentTraceEvent) => self.send({ type: 'TRACE', event }),
        }),
        onDone: {
          target: 'evaluatingRun',
          actions: assign({
            run: ({ event }) => event.output,
            approvalStatus: null,
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
        input: ({ context }) => context.run as AgentRunState,
        onDone: {
          target: 'evaluatingRun',
          actions: assign({
            run: ({ event }) => event.output,
            approvalStatus: null,
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
        CANCEL: 'canceling',
        CLEAR: 'clearing',
      },
    },
    canceling: {
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
            approvalStatus: null,
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
          run: context.run,
          runId: context.runId,
        }),
        onDone: {
          target: 'canceled',
          actions: assign(emptyContext),
        },
        onError: {
          target: 'canceled',
          actions: assign({
            transcript: [],
            trace: [],
            contextId: null,
            runId: null,
            contextReady: false,
            pending: null,
            run: null,
            approvalStatus: null,
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
            approvalStatus: null,
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
          guard: ({ context }) => isRecoverablePause(context.run),
          target: 'approvalRequired',
        },
        {
          guard: ({ context }) => context.run?.status === 'paused',
          target: 'retrying',
        },
        {
          guard: ({ context }) => (
            context.run?.status === 'finished' && context.run.response != null
          ),
          target: 'idle',
          actions: assign({
            transcript: ({ context }) => [
              ...context.transcript,
              assistantEntry(context.run!.response!, context.transcript.length + 1),
            ],
            pending: null,
            approvalStatus: null,
            error: null,
          }),
        },
        {
          target: 'failed',
          actions: assign({
            approvalStatus: null,
            error: ({ context }) => agentRunError(context.run as AgentRunState),
          }),
        },
      ],
    },
    failed: {
      on: {
        CANCEL: 'canceled',
        RETRY: [
          {
            guard: ({ context }) => context.run?.status === 'paused',
            target: 'resuming',
          },
          {
            guard: ({ context }) => context.run !== null,
            target: 'retrying',
          },
          {
            guard: ({ context }) => !context.contextReady,
            target: 'preparing',
          },
          { target: 'streaming' },
        ],
        SEND: {
          target: 'preparing',
          actions: assign({
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
            approvalStatus: null,
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
  const detail = run.stop_reason || run.status || 'unknown state'
  return new Error(`Agent run did not finish: ${detail}`)
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
