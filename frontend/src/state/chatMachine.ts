import { assign, createActor, fromPromise, setup } from 'xstate'
import type {
  AgentRunState,
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
  prepareChatContext,
  resumeChatRun,
  retryChatRun,
  startChatRun,
  type ChatRequestInput,
  type ChatResumeInput,
} from '../runtime/chatRuntime'

type ChatPendingRequest = {
  submission: ChatSubmission
  tools: ToolDefinition[]
}

export type ChatMachineContext = {
  transcript: ChatTranscriptEntry[]
  contextId: string | null
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
  | { type: 'CLEAR' }

export type { ChatRequestInput, ChatResumeInput }

const emptyContext = (): ChatMachineContext => ({
  transcript: [],
  contextId: null,
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
    sendChat: fromPromise<AgentRunState, ChatRequestInput>(({ input, signal }) => (
      startChatRun(input, signal)
    )),
    resumeChat: fromPromise<AgentRunState, ChatResumeInput>(({ input, signal }) => (
      resumeChatRun(input, signal)
    )),
    retryChat: fromPromise<AgentRunState, AgentRunState>(({ input, signal }) => (
      retryChatRun(input, signal)
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
            pending: ({ event }) => ({
              submission: event.submission,
              tools: event.tools,
            }),
            transcript: ({ context, event }) => [
              ...context.transcript,
              userEntry(event.submission, context.transcript.length + 1),
            ],
            run: null,
            approvalStatus: null,
            error: null,
          }),
        },
        CLEAR: {
          actions: assign(emptyContext),
        },
      },
    },
    preparing: {
      always: {
        guard: ({ context }) => context.contextReady,
        target: 'sending',
      },
      invoke: {
        id: 'prepareContext',
        src: 'prepareContext',
        input: ({ context }) => context.contextId as string,
        onDone: {
          target: 'sending',
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
        CLEAR: {
          target: 'idle',
          actions: assign(emptyContext),
        },
      },
    },
    sending: {
      invoke: {
        id: 'sendChat',
        src: 'sendChat',
        input: ({ context }) => ({
          contextId: context.contextId as string,
          submission: (context.pending as ChatPendingRequest).submission,
          tools: (context.pending as ChatPendingRequest).tools,
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
        CLEAR: {
          target: 'idle',
          actions: assign(emptyContext),
        },
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
        CLEAR: {
          target: 'idle',
          actions: assign(emptyContext),
        },
      },
    },
    resuming: {
      invoke: {
        id: 'resumeChat',
        src: 'resumeChat',
        input: ({ context }) => ({
          run: context.run as AgentRunState,
          status: context.approvalStatus as Extract<
            ToolApprovalStatus,
            'approved' | 'denied'
          >,
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
        CLEAR: {
          target: 'idle',
          actions: assign(emptyContext),
        },
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
        CLEAR: {
          target: 'idle',
          actions: assign(emptyContext),
        },
      },
    },
    evaluatingRun: {
      always: [
        {
          guard: ({ context }) => context.run?.status === 'paused',
          target: 'approvalRequired',
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
          { target: 'sending' },
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
            run: null,
            approvalStatus: null,
            error: null,
          }),
        },
        CLEAR: {
          target: 'idle',
          actions: assign(emptyContext),
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
