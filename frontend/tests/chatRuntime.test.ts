import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AgentRunState } from '../src/api'
import {
  approvalDecisions,
  startChatRun,
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

  it('starts a multi-round agent run with the workspace tools', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(finishedRun()), {
      status: 201,
      headers: { 'content-type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await startChatRun(requestInput(), new AbortController().signal)

    const [path, options] = fetchMock.mock.calls[0] as [string, RequestInit]
    const body = JSON.parse(String(options.body)) as Record<string, unknown>
    expect(path).toBe('/agent-runs')
    expect(body).toMatchObject({
      provider_id: 'main',
      context_id: 'context-1',
      model_id: 'model-1',
      max_tool_rounds: 4,
      pause_on_approval: true,
      tools: [{ name: 'read_file' }],
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
