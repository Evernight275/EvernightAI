import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AgentRunState } from '../src/api'
import {
  approvalDecisions,
  clearChatContext,
  loadChatSession,
  retryChatRun,
  streamChatRun,
  type ChatRequestInput,
} from '../src/runtime/chatRuntime'

describe('chat runtime', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', {
      getItem: vi.fn(() => null),
    })
    vi.stubGlobal('window', {
      EVERNIGHTAI_API_KEY: '',
      EVERNIGHTAI_ACCESS_TOKEN: '',
    })
  })

  it('builds one decision for every pending approval', () => {
    const run = finishedRun()
    run.pending_approval_requests = [
      {
        approval_id: 'approval-1',
        tool_call_id: 'call-1',
        tool_name: 'read_file',
      },
      {
        approval_id: 'approval-2',
        tool_call_id: 'call-2',
        tool_name: 'write_file',
      },
    ]

    expect(approvalDecisions(run, {
      'approval-1': 'approved',
      'approval-2': 'denied',
    })).toEqual([
      {
        approval_id: 'approval-1',
        tool_call_id: 'call-1',
        status: 'approved',
      },
      {
        approval_id: 'approval-2',
        tool_call_id: 'call-2',
        status: 'denied',
      },
    ])
  })

  it('only permits an empty decision set when no approval is pending', () => {
    expect(approvalDecisions(finishedRun(), {})).toEqual([])

    const run = finishedRun()
    run.pending_approval_requests = [{
      approval_id: 'approval-1',
      tool_call_id: 'call-1',
      tool_name: 'write_file',
    }]
    expect(() => approvalDecisions(run, {})).toThrow(
      'Missing decision for tool approval: approval-1',
    )
  })

  it('streams the agent trace, then reads the persisted run state', async () => {
    const stream = [
      'event: run_started\ndata: {"event_type":"run_started"}\n\n',
      'data: [DONE]\n\n',
    ].join('')
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(stream, {
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify(finishedRun()), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }))
    vi.stubGlobal('fetch', fetchMock)

    const run = await streamChatRun(requestInput(), new AbortController().signal)
    const [streamPath, streamOptions] = fetchMock.mock.calls[0] as [string, RequestInit]
    const streamBody = JSON.parse(String(streamOptions.body)) as Record<string, unknown>

    expect(run.run_id).toBe('run-1')
    expect(streamPath).toBe('/agent-runs/stream')
    expect(streamBody).toMatchObject({
      context_id: 'context-1',
      max_tool_rounds: 4,
      pause_on_approval: true,
    })
    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      `/agent-runs/${String((streamBody.metadata as Record<string, unknown>).run_id)}`,
    )
  })

  it('tags a selected session on its agent run', async () => {
    const stream = 'data: [DONE]\n\n'
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(stream, {
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify(finishedRun()), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }))
    vi.stubGlobal('fetch', fetchMock)

    await streamChatRun({
      ...requestInput(),
      sessionId: 'session-1',
    }, new AbortController().signal)
    const options = fetchMock.mock.calls[0]?.[1] as RequestInit
    const body = JSON.parse(String(options.body)) as {
      metadata: Record<string, unknown>
    }

    expect(body.metadata.session_id).toBe('session-1')
  })

  it('recovers persisted state when the stream transport fails', async () => {
    const persisted = { ...finishedRun(), run_id: 'run-recovered' }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response('stream disconnected', { status: 502 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(persisted), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }))
    vi.stubGlobal('fetch', fetchMock)
    const input = { ...requestInput(), runId: 'run-recovered' }

    const run = await streamChatRun(input, new AbortController().signal)

    expect(run.run_id).toBe('run-recovered')
    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
      '/agent-runs/stream',
      '/agent-runs/run-recovered',
    ])
  })

  it('streams a retry under a caller-known run id', async () => {
    const stream = 'data: [DONE]\n\n'
    const retried = { ...finishedRun(), run_id: 'run-retried' }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(stream, {
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify(retried), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await retryChatRun({
      run: { ...finishedRun(), status: 'failed' },
      runId: 'run-retried',
    }, new AbortController().signal)
    const [path, options] = fetchMock.mock.calls[0] as [string, RequestInit]

    expect(result.run_id).toBe('run-retried')
    expect(path).toBe('/agent-runs/run-1/retry/stream')
    expect(JSON.parse(String(options.body))).toEqual({
      retried_run_id: 'run-retried',
    })
    expect(fetchMock.mock.calls[1]?.[0]).toBe('/agent-runs/run-retried')
  })

  it('cancels a known run before deleting its context', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(finishedRun()), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)

    await clearChatContext({
      contextId: 'context-1',
      run: { ...finishedRun(), status: 'running' },
    }, new AbortController().signal)

    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
      '/agent-runs/run-1/cancel',
      '/contexts/context-1/delete',
    ])
  })

  it('can cancel a streamed run before its final state is returned', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(finishedRun()), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)

    await clearChatContext({
      contextId: 'context-1',
      run: null,
      runId: 'run-streaming-1',
    }, new AbortController().signal)

    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
      '/agent-runs/run-streaming-1/cancel',
      '/contexts/context-1/delete',
    ])
  })

  it('cancels a preallocated retry instead of its terminal source run', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(finishedRun()), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)

    await clearChatContext({
      contextId: 'context-1',
      run: { ...finishedRun(), status: 'failed' },
      runId: 'run-retried',
    }, new AbortController().signal)

    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
      '/agent-runs/run-retried/cancel',
      '/contexts/context-1/delete',
    ])
  })

  it('cancels the old run and loads a selected session transcript', async () => {
    const context = {
      context_id: 'context-2',
      messages: [{
        role: 'user',
        content: [{ type: 'text', text: 'stored message' }],
      }],
    }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        ...finishedRun(),
        run_id: 'run-old',
        status: 'canceled',
      }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify(context), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }))
    vi.stubGlobal('fetch', fetchMock)

    const snapshot = await loadChatSession({
      session: {
        session_id: 'session-2',
        context_id: 'context-2',
      },
      currentRun: { ...finishedRun(), run_id: 'run-old', status: 'paused' },
      currentRunId: 'run-old',
    }, new AbortController().signal)

    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
      '/agent-runs/run-old/cancel',
      '/contexts/context-2',
    ])
    expect(snapshot.transcript[0]?.text).toBe('stored message')
  })

  it('clears a session context without deleting it', async () => {
    const context = {
      context_id: 'context-1',
      messages: [{ role: 'user', content: [{ type: 'text', text: 'old' }] }],
      metadata: { session_id: 'session-1' },
    }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(context), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        ...context,
        messages: [],
      }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }))
    vi.stubGlobal('fetch', fetchMock)

    await clearChatContext({
      contextId: 'context-1',
      sessionId: 'session-1',
      run: finishedRun(),
    }, new AbortController().signal)

    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
      '/contexts/context-1',
      '/contexts/context-1',
    ])
    const replaceOptions = fetchMock.mock.calls[1]?.[1] as RequestInit
    expect(JSON.parse(String(replaceOptions.body))).toMatchObject({ messages: [] })
  })
})

function requestInput(): ChatRequestInput {
  return {
    contextId: 'context-1',
    submission: {
      providerId: 'main',
      modelId: 'model-1',
      text: 'read the file',
    },
    tools: [{
      name: 'read_file',
      description: 'Read a file',
      parameters_schema: { type: 'object' },
    }],
  }
}

function finishedRun(): AgentRunState {
  return {
    run_id: 'run-1',
    request: {
      provider_id: 'main',
      context_id: 'context-1',
      model_id: 'model-1',
    },
    status: 'finished',
  }
}
