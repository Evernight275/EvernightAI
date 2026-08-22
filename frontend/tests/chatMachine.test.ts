import { createActor, fromPromise, waitFor } from 'xstate'
import { describe, expect, it, vi } from 'vitest'
import type {
  AgentRunState,
  ChatResponse,
  ToolDefinition,
} from '../src/api'
import type { ChatSubmission } from '../src/domain/chat'
import type {
  ChatClearInput,
  ChatRequestInput,
  ChatResumeInput,
} from '../src/runtime/chatRuntime'
import { chatMachine } from '../src/state/chatMachine'

describe('chatMachine', () => {
  it('records both sides of a successful agent run', async () => {
    const actor = actorWithServices(async ({ input }) => finishedRun(input, 'answer'))

    actor.start()
    actor.send(sendEvent('question'))
    const snapshot = await waitFor(actor, (state) => (
      state.matches('idle') && state.context.transcript.length === 2
    ))

    expect(snapshot.context.transcript.map((entry) => [entry.role, entry.text])).toEqual([
      ['user', 'question'],
      ['assistant', 'answer'],
    ])
    expect(snapshot.context.pending).toBeNull()
    actor.stop()
  })

  it('sends tools and reuses the server context on later turns', async () => {
    const requests: ChatRequestInput[] = []
    const actor = actorWithServices(async ({ input }) => {
      requests.push(input)
      return finishedRun(input, `answer-${requests.length}`)
    })

    actor.start()
    actor.send(sendEvent('first'))
    await waitFor(actor, (state) => state.matches('idle') && state.context.transcript.length === 2)
    actor.send(sendEvent('second'))
    await waitFor(actor, (state) => state.matches('idle') && state.context.transcript.length === 4)

    expect(requests[0]?.tools).toEqual([tool()])
    expect(requests[1]?.contextId).toBe(requests[0]?.contextId)
    expect(requests[1]?.submission.text).toBe('second')
    actor.stop()
  })

  it('retries a failed request without duplicating the user entry', async () => {
    const sender = vi.fn()
      .mockRejectedValueOnce(new Error('provider unavailable'))
      .mockImplementationOnce(async ({ input }: { input: ChatRequestInput }) => (
        finishedRun(input, 'recovered')
      ))
    const actor = actorWithServices(sender)

    actor.start()
    actor.send(sendEvent('question'))
    await waitFor(actor, (state) => state.matches('failed'))
    actor.send({ type: 'RETRY' })
    const snapshot = await waitFor(actor, (state) => (
      state.matches('idle') && state.context.transcript.length === 2
    ))

    expect(sender).toHaveBeenCalledTimes(2)
    expect(snapshot.context.transcript.map((entry) => entry.role)).toEqual([
      'user',
      'assistant',
    ])
    actor.stop()
  })

  it('uses the agent retry endpoint for a returned failed run', async () => {
    const retries: AgentRunState[] = []
    const actor = actorWithServices(
      async ({ input }) => failedRun(input),
      undefined,
      async ({ input }) => {
        retries.push(input)
        return finishedResumedRun(input, 'recovered run')
      },
    )

    actor.start()
    actor.send(sendEvent('question'))
    await waitFor(actor, (state) => state.matches('failed'))
    actor.send({ type: 'RETRY' })
    const snapshot = await waitFor(actor, (state) => (
      state.matches('idle') && state.context.transcript.length === 2
    ))

    expect(retries.map((run) => run.run_id)).toEqual(['run-failed'])
    expect(snapshot.context.transcript[1]?.text).toBe('recovered run')
    actor.stop()
  })

  it('retries an unrecoverable paused run instead of requesting approval', async () => {
    const resumes: ChatResumeInput[] = []
    const retries: AgentRunState[] = []
    const actor = actorWithServices(
      async ({ input }) => unrecoverablePausedRun(input),
      async ({ input }) => {
        resumes.push(input)
        return input.run
      },
      async ({ input }) => {
        retries.push(input)
        return finishedResumedRun(input, 'recovered pause')
      },
    )

    actor.start()
    actor.send(sendEvent('recover me'))
    const snapshot = await waitFor(actor, (state) => (
      state.matches('idle') && state.context.transcript.length === 2
    ))

    expect(resumes).toHaveLength(0)
    expect(retries.map((run) => run.run_id)).toEqual(['run-unrecoverable'])
    expect(snapshot.context.transcript[1]?.text).toBe('recovered pause')
    actor.stop()
  })

  it('resumes a paused tool call after approval', async () => {
    const resumes: ChatResumeInput[] = []
    const actor = actorWithServices(
      async ({ input }) => pausedRun(input),
      async ({ input }) => {
        resumes.push(input)
        return finishedResumedRun(input.run, 'tool complete')
      },
    )

    actor.start()
    actor.send(sendEvent('use the tool'))
    await waitFor(actor, (state) => state.matches('approvalRequired'))
    actor.send({ type: 'APPROVE' })
    const snapshot = await waitFor(actor, (state) => (
      state.matches('idle') && state.context.transcript.length === 2
    ))

    expect(resumes).toHaveLength(1)
    expect(resumes[0]?.status).toBe('approved')
    expect(snapshot.context.transcript[1]?.text).toBe('tool complete')
    actor.stop()
  })

  it('aborts an active agent run when local history is cleared', async () => {
    const requestSignals: AbortSignal[] = []
    const actor = actorWithServices(({ signal }) => {
      requestSignals.push(signal)
      return new Promise<AgentRunState>(() => undefined)
    })

    actor.start()
    actor.send(sendEvent('question'))
    await vi.waitFor(() => expect(requestSignals).toHaveLength(1))
    actor.send({ type: 'CLEAR' })

    expect(requestSignals[0]?.aborted).toBe(true)
    await waitFor(actor, (state) => state.matches('canceled'))
    expect(actor.getSnapshot().context.transcript).toEqual([])
    actor.stop()
  })

  it('records streamed tool trace while the run is still active', async () => {
    const actor = actorWithServices(({ input }) => {
      input.onTrace?.({
        event_type: 'tool_completed',
        tool_call: {
          tool_call_id: 'call-1',
          tool_call: { name: 'read_file' },
        },
      })
      return new Promise<AgentRunState>(() => undefined)
    })

    actor.start()
    actor.send(sendEvent('stream tool'))
    const snapshot = await waitFor(actor, (state) => (
      state.matches('streaming') && state.context.trace.length === 1
    ))

    expect(snapshot.context.trace[0]?.event_type).toBe('tool_completed')
    actor.send({ type: 'CANCEL' })
    await waitFor(actor, (state) => state.matches('canceled'))
    actor.stop()
  })

  it('enters canceled without clearing local history when explicitly canceled', async () => {
    const requestSignals: AbortSignal[] = []
    const actor = actorWithServices(({ signal }) => {
      requestSignals.push(signal)
      return new Promise<AgentRunState>(() => undefined)
    })

    actor.start()
    actor.send(sendEvent('cancel me'))
    await vi.waitFor(() => expect(requestSignals).toHaveLength(1))
    actor.send({ type: 'CANCEL' })
    await waitFor(actor, (state) => state.matches('canceled'))

    expect(requestSignals[0]?.aborted).toBe(true)
    expect(actor.getSnapshot().context.transcript[0]?.text).toBe('cancel me')
    actor.stop()
  })
})

function actorWithServices(
  sender: (
    options: { input: ChatRequestInput; signal: AbortSignal },
  ) => Promise<AgentRunState>,
  resumer: (
    options: { input: ChatResumeInput; signal: AbortSignal },
  ) => Promise<AgentRunState> = async ({ input }) => input.run,
  retryer: (
    options: { input: AgentRunState; signal: AbortSignal },
  ) => Promise<AgentRunState> = async ({ input }) => input,
  clearer: (
    _options: { input: ChatClearInput; signal: AbortSignal },
  ) => Promise<void> = async () => undefined,
) {
  return createActor(chatMachine.provide({
    actors: {
      prepareContext: fromPromise<void, string>(async () => undefined),
      streamChat: fromPromise<AgentRunState, ChatRequestInput>(sender),
      resumeChat: fromPromise<AgentRunState, ChatResumeInput>(resumer),
      retryChat: fromPromise<AgentRunState, AgentRunState>(retryer),
      clearChat: fromPromise<void, ChatClearInput>(clearer),
    },
  }))
}

function sendEvent(text: string) {
  return {
    type: 'SEND' as const,
    submission: submission(text),
    tools: [tool()],
  }
}

function submission(text: string): ChatSubmission {
  return {
    providerId: 'main',
    modelId: 'model-1',
    text,
  }
}

function tool(): ToolDefinition {
  return {
    name: 'read_file',
    description: 'Read a file',
    parameters_schema: { type: 'object' },
  }
}

function finishedRun(input: ChatRequestInput, text: string): AgentRunState {
  return {
    run_id: `run-${text}`,
    request: agentRequest(input),
    status: 'finished',
    response: response(text),
    steps: [],
    pending_approval_requests: [],
  }
}

function pausedRun(input: ChatRequestInput): AgentRunState {
  return {
    run_id: 'run-paused',
    request: agentRequest(input),
    status: 'paused',
    response: response(''),
    pending_approval_requests: [{
      approval_id: 'approval-1',
      tool_call_id: 'call-1',
      tool_name: 'read_file',
      safety_level: 'sensitive',
    }],
  }
}

function unrecoverablePausedRun(input: ChatRequestInput): AgentRunState {
  return {
    ...pausedRun(input),
    run_id: 'run-unrecoverable',
    metadata: {
      agent_runtime: {
        recovery_eligible: false,
      },
    },
  }
}

function failedRun(input: ChatRequestInput): AgentRunState {
  return {
    run_id: 'run-failed',
    request: agentRequest(input),
    status: 'failed',
    stop_reason: 'tool_error',
  }
}

function finishedResumedRun(run: AgentRunState, text: string): AgentRunState {
  return {
    ...run,
    status: 'finished',
    response: response(text),
    pending_approval_requests: [],
  }
}

function agentRequest(input: ChatRequestInput) {
  return {
    provider_id: input.submission.providerId,
    context_id: input.contextId,
    model_id: input.submission.modelId,
    messages: [{
      role: 'user' as const,
      content: [{ type: 'text', text: input.submission.text }],
    }],
    tools: input.tools,
  }
}

function response(text: string): ChatResponse {
  return {
    response_id: `response-${text}`,
    model_id: 'model-1',
    message: {
      role: 'assistant',
      content: [{ type: 'text', text }],
    },
    finish_reason: 'stop',
  }
}
