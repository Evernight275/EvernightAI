import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AgentRunState } from '../src/api'
import {
  approvalDecisions,
  clearChatContext,
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

    expect(approvalDecisions(run, 'denied')).toEqual([
      {
        approval_id: 'approval-1',
        tool_call_id: 'call-1',
        status: 'denied',
      },
      {
        approval_id: 'approval-2',
        tool_call_id: 'call-2',
        status: 'denied',
      },
    ])
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
