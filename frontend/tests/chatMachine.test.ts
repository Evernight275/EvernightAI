import { createActor, fromPromise, waitFor } from 'xstate'
import { describe, expect, it, vi } from 'vitest'
import type {
  AgentRunState,
  ChatResponse,
  ToolDefinition,
} from '../src/api'
import type { ChatSubmission } from '../src/domain/chat'
import type {
  ChatCancelInput,
  ChatClearInput,
  ChatRequestInput,
  ChatResumeInput,
  ChatRetryInput,
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
    const retries: ChatRetryInput[] = []
    const actor = actorWithServices(
      async ({ input }) => failedRun(input),
      undefined,
      async ({ input }) => {
        retries.push(input)
        return finishedRetriedRun(input, 'recovered run')
      },
    )

    actor.start()
    actor.send(sendEvent('question'))
    await waitFor(actor, (state) => state.matches('failed'))
    actor.send({ type: 'RETRY' })
    const snapshot = await waitFor(actor, (state) => (
      state.matches('idle') && state.context.transcript.length === 2
    ))

    expect(retries.map((retry) => retry.run.run_id)).toEqual(['run-failed'])
    expect(snapshot.context.runId).toBe(retries[0]?.runId)
    expect(snapshot.context.transcript[1]?.text).toBe('recovered run')
    actor.stop()
  })

  it('retries an unrecoverable paused run instead of requesting approval', async () => {
    const resumes: ChatResumeInput[] = []
    const retries: ChatRetryInput[] = []
    const actor = actorWithServices(
      async ({ input }) => unrecoverablePausedRun(input),
      async ({ input }) => {
        resumes.push(input)
        return input.run
      },
      async ({ input }) => {
        retries.push(input)
        return finishedRetriedRun(input, 'recovered pause')
      },
    )

    actor.start()
    actor.send(sendEvent('recover me'))
    const snapshot = await waitFor(actor, (state) => (
      state.matches('idle') && state.context.transcript.length === 2
    ))

    expect(resumes).toHaveLength(0)
    expect(retries.map((retry) => retry.run.run_id)).toEqual(['run-unrecoverable'])
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
    actor.send({ type: 'APPROVE', approvalId: 'approval-1' })
    const snapshot = await waitFor(actor, (state) => (
      state.matches('idle') && state.context.transcript.length === 2
    ))

    expect(resumes).toHaveLength(1)
    expect(resumes[0]?.approvalStatuses).toEqual({ 'approval-1': 'approved' })
    expect(snapshot.context.transcript[1]?.text).toBe('tool complete')
    actor.stop()
  })

  it('resumes a paused tool call after denial', async () => {
    const resumes: ChatResumeInput[] = []
    const actor = actorWithServices(
      async ({ input }) => pausedRun(input),
      async ({ input }) => {
        resumes.push(input)
        return finishedResumedRun(input.run, 'denial handled')
      },
    )

    actor.start()
    actor.send(sendEvent('do not use the tool'))
    await waitFor(actor, (state) => state.matches('approvalRequired'))
    actor.send({ type: 'DENY', approvalId: 'approval-1' })
    const snapshot = await waitFor(actor, (state) => (
      state.matches('idle') && state.context.transcript.length === 2
    ))

    expect(resumes).toHaveLength(1)
    expect(resumes[0]?.approvalStatuses).toEqual({ 'approval-1': 'denied' })
    expect(snapshot.context.transcript[1]?.text).toBe('denial handled')
    actor.stop()
  })

  it('keeps the approval decision when a resume request is retried', async () => {
    const statuses: ChatResumeInput['approvalStatuses'][] = []
    const resumer = vi.fn(async ({ input }: { input: ChatResumeInput }) => {
      statuses.push(input.approvalStatuses)
      if (statuses.length === 1) {
        throw new Error('resume unavailable')
      }
      return finishedResumedRun(input.run, 'resumed after retry')
    })
    const actor = actorWithServices(
      async ({ input }) => pausedRun(input),
      resumer,
    )

    actor.start()
    actor.send(sendEvent('approve and retry'))
    await waitFor(actor, (state) => state.matches('approvalRequired'))
    actor.send({ type: 'APPROVE', approvalId: 'approval-1' })
    await waitFor(actor, (state) => state.matches('failed'))
    actor.send({ type: 'RETRY' })
    await waitFor(actor, (state) => state.matches('idle'))

    expect(statuses).toEqual([
      { 'approval-1': 'approved' },
      { 'approval-1': 'approved' },
    ])
    actor.stop()
  })

  it('separates a manual pause from tool approval', async () => {
    const resumes: ChatResumeInput[] = []
    const actor = actorWithServices(
      async ({ input }) => manualPausedRun(input),
      async ({ input }) => {
        resumes.push(input)
        return finishedResumedRun(input.run, 'continued')
      },
    )

    actor.start()
    actor.send(sendEvent('pause externally'))
    await waitFor(actor, (state) => state.matches('resumeRequired'))
    actor.send({ type: 'RESUME' })
    await waitFor(actor, (state) => state.matches('idle'))

    expect(resumes).toHaveLength(1)
    expect(resumes[0]?.approvalStatuses).toEqual({})
    actor.stop()
  })

  it('collects an independent decision for every pending approval', async () => {
    const resumes: ChatResumeInput[] = []
    const actor = actorWithServices(
      async ({ input }) => pausedRunWithTwoApprovals(input),
      async ({ input }) => {
        resumes.push(input)
        return finishedResumedRun(input.run, 'both handled')
      },
    )

    actor.start()
    actor.send(sendEvent('use selected tools'))
    await waitFor(actor, (state) => state.matches('approvalRequired'))
    actor.send({ type: 'APPROVE', approvalId: 'approval-1' })
    expect(actor.getSnapshot().matches('approvalRequired')).toBe(true)
    actor.send({ type: 'DENY', approvalId: 'approval-2' })
    await waitFor(actor, (state) => state.matches('idle'))

    expect(resumes[0]?.approvalStatuses).toEqual({
      'approval-1': 'approved',
      'approval-2': 'denied',
    })
    actor.stop()
  })

  it('allocates a fresh run id when sending after a terminal failure', async () => {
    const requests: ChatRequestInput[] = []
    const actor = actorWithServices(async ({ input }) => {
      requests.push(input)
      return requests.length === 1
        ? failedRun(input)
        : finishedRun(input, 'new request')
    })

    actor.start()
    actor.send(sendEvent('first'))
    await waitFor(actor, (state) => state.matches('failed'))
    actor.send(sendEvent('second'))
    await waitFor(actor, (state) => state.matches('idle'))

    expect(requests[0]?.runId).not.toBe(requests[1]?.runId)
    actor.stop()
  })

  it('cancels the newly allocated run while retrying', async () => {
    const retries: ChatRetryInput[] = []
    const cancellations: ChatCancelInput[] = []
    const actor = actorWithServices(
      async ({ input }) => failedRun(input),
      undefined,
      ({ input }) => {
        retries.push(input)
        return new Promise<AgentRunState>(() => undefined)
      },
      undefined,
      async ({ input }) => {
        cancellations.push(input)
        return null
      },
    )

    actor.start()
    actor.send(sendEvent('retry then cancel'))
    await waitFor(actor, (state) => state.matches('failed'))
    actor.send({ type: 'RETRY' })
    await waitFor(actor, (state) => state.matches('retrying'))
    actor.send({ type: 'CANCEL' })
    await waitFor(actor, (state) => state.matches('canceled'))

    expect(retries[0]?.runId).not.toBe('run-failed')
    expect(cancellations[0]?.runId).toBe(retries[0]?.runId)
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
    options: { input: ChatRetryInput; signal: AbortSignal },
  ) => Promise<AgentRunState> = async ({ input }) => input.run,
  clearer: (
    _options: { input: ChatClearInput; signal: AbortSignal },
  ) => Promise<void> = async () => undefined,
  canceler: (
    _options: { input: ChatCancelInput; signal: AbortSignal },
  ) => Promise<AgentRunState | null> = async () => null,
) {
  return createActor(chatMachine.provide({
    actors: {
      prepareContext: fromPromise<void, string>(async () => undefined),
      streamChat: fromPromise<AgentRunState, ChatRequestInput>(sender),
      resumeChat: fromPromise<AgentRunState, ChatResumeInput>(resumer),
      retryChat: fromPromise<AgentRunState, ChatRetryInput>(retryer),
      clearChat: fromPromise<void, ChatClearInput>(clearer),
      cancelChat: fromPromise<AgentRunState | null, ChatCancelInput>(canceler),
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

function pausedRunWithTwoApprovals(input: ChatRequestInput): AgentRunState {
  const run = pausedRun(input)
  run.pending_approval_requests = [
    ...(run.pending_approval_requests || []),
    {
      approval_id: 'approval-2',
      tool_call_id: 'call-2',
      tool_name: 'write_file',
      safety_level: 'restricted',
    },
  ]
  return run
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

function manualPausedRun(input: ChatRequestInput): AgentRunState {
  return {
    ...pausedRun(input),
    run_id: 'run-manually-paused',
    pending_approval_requests: [],
    metadata: {
      agent_runtime: {
        manual_pause: true,
        recovery_eligible: true,
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

function finishedRetriedRun(input: ChatRetryInput, text: string): AgentRunState {
  return {
    ...finishedResumedRun(input.run, text),
    run_id: input.runId,
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
