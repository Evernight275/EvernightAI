import { describe, expect, it } from 'vitest'
import {
  applyChatTrace,
  completeStreamedResponse,
  type ChatTranscriptEntry,
} from '../src/domain/chat'
import type { ChatResponse } from '../src/api'

const response = (text: string): ChatResponse => ({
  model_id: 'model',
  message: { role: 'assistant', content: [{ type: 'text', text }] },
})

describe('streamed transcript', () => {
  it('separates tool rounds and keeps final reconciliation idempotent', () => {
    let entries: ChatTranscriptEntry[] = []
    entries = applyChatTrace(
      entries,
      { event_type: 'chat_delta', text_delta: 'Checking files.' },
      'run',
    )
    entries = applyChatTrace(
      entries,
      { event_type: 'chat_completed', response: response('Checking files.') },
      'run',
    )
    entries = applyChatTrace(entries, { event_type: 'tool_completed' }, 'run')
    entries = applyChatTrace(entries, { event_type: 'chat_delta', text_delta: 'The answer' }, 'run')
    entries = applyChatTrace(entries, { event_type: 'chat_delta', text_delta: ' is 42.' }, 'run')
    entries = completeStreamedResponse(entries, response('The answer is 42.'), 'run')
    entries = completeStreamedResponse(entries, response('The answer is 42.'), 'run')
    expect(entries.map((entry) => entry.text)).toEqual(['Checking files.', 'The answer is 42.'])
  })

  it('ignores nontext events and distinguishes retries from the interrupted run', () => {
    let entries = applyChatTrace(
      [],
      { event_type: 'chat_completed', response: response('') },
      'run',
    )
    expect(entries).toEqual([])
    entries = applyChatTrace(entries, { event_type: 'chat_delta', text_delta: 'partial' }, 'run')
    entries = applyChatTrace(
      entries,
      { event_type: 'chat_delta', text_delta: 'new answer' },
      'retry',
    )
    expect(entries.map((entry) => entry.text)).toEqual(['partial', 'new answer'])
  })
})

import { transcriptFromMessages } from '../src/domain/chat'
const call = {
  tool_call_id: 'read-1',
  tool_call: { name: 'read_text_file', arguments: { path: 'README.md' } },
}

it('interleaves text, deduplicated tool progress, and the final response', () => {
  let entries = applyChatTrace([], { event_type: 'chat_delta', text_delta: '先读取说明。' }, 'run')
  const toolResponse = response('先读取说明。')
  toolResponse.message.tool_calls = [call]
  entries = applyChatTrace(entries, { event_type: 'chat_completed', response: toolResponse }, 'run')
  entries = applyChatTrace(
    entries,
    { event_type: 'tool_approval_requested', tool_call: call },
    'run',
  )
  expect(entries[1]?.toolActivity?.status).toBe('approval')
  entries = applyChatTrace(
    entries,
    {
      event_type: 'tool_completed',
      tool_call: call,
      tool_result: {
        tool_call_id: 'read-1',
        tool_call_result: { content: 'Project documentation' },
      },
    },
    'run',
  )
  entries = applyChatTrace(entries, { event_type: 'chat_completed', response: toolResponse }, 'run')
  expect(entries).toHaveLength(2)
  expect(entries[1]?.toolActivity?.status).toBe('completed')
  entries = applyChatTrace(
    entries,
    { event_type: 'chat_delta', text_delta: '这是项目总结。' },
    'run',
  )
  entries = completeStreamedResponse(entries, response('这是项目总结。'), 'run')
  entries = completeStreamedResponse(entries, response('这是项目总结。'), 'run')
  expect(entries.map((entry) => entry.toolActivity?.name || entry.text)).toEqual([
    '先读取说明。',
    'read_text_file',
    '这是项目总结。',
  ])
  expect(entries[1]?.toolActivity?.argumentsText).toContain('README.md')
})

it('restores tool-only rounds and failures in history without mixing repeated IDs across turns', () => {
  const entries = transcriptFromMessages([
    { role: 'user', content: [{ type: 'text', text: 'inspect' }] },
    { role: 'assistant', tool_calls: [call] },
    { role: 'tool', tool_call_id: 'read-1', content: [{ type: 'text', text: 'first result' }] },
    { role: 'assistant', content: [{ type: 'text', text: 'answer' }] },
    { role: 'user', content: [{ type: 'text', text: 'again' }] },
    { role: 'assistant', tool_calls: [call] },
    {
      role: 'tool',
      tool_call_id: 'read-1',
      metadata: { error: true },
      content: [{ type: 'text', text: 'failed' }],
    },
  ])
  const tools = entries.filter((entry) => entry.toolActivity)
  expect(tools).toHaveLength(2)
  expect(tools.map((entry) => entry.toolActivity?.status)).toEqual(['completed', 'failed'])
  expect(tools[0]?.toolActivity?.resultText).toBe('first result')
  expect(tools[1]?.toolActivity?.argumentsText).toContain('README.md')
})

it('retains identical prose separated by a tool round', () => {
  const first = response('继续检查。')
  first.message.tool_calls = [call]
  let entries = applyChatTrace([], { event_type: 'chat_completed', response: first }, 'run')
  entries = applyChatTrace(
    entries,
    { event_type: 'tool_failed', tool_call: call, error_message: 'missing' },
    'run',
  )
  entries = completeStreamedResponse(entries, response('继续检查。'), 'run')
  expect(entries).toHaveLength(3)
  expect(entries[1]?.toolActivity?.status).toBe('failed')
})

import { reconcileRunTranscript, userEntry } from '../src/domain/chat'
import type { AgentRunState, AgentTraceEvent } from '../src/api'

it('restores all five phases from persisted events without duplicating text or tools', () => {
  const initial = [userEntry({ providerId: 'p', modelId: 'm', text: '检查' }, 0)]
  const toolResponse = response('检查文件。')
  toolResponse.message.tool_calls = [call]
  const events: AgentTraceEvent[] = [
    { sequence: 1, event_type: 'chat_delta', text_delta: '检查' },
    { sequence: 2, event_type: 'chat_completed', response: toolResponse },
    { sequence: 3, event_type: 'tool_approval_requested', tool_call: call },
    {
      sequence: 4,
      event_type: 'tool_approval_decided',
      tool_call: call,
      metadata: { allowed: true },
    },
    { sequence: 5, event_type: 'tool_started', tool_call: call },
    {
      sequence: 6,
      event_type: 'tool_failed',
      tool_call: call,
      error_type: 'FileNotFoundError',
      error_message: 'missing README.md',
    },
  ]
  let entries = initial
  const phases = []
  for (const event of events) {
    entries = applyChatTrace(entries, event, 'run')
    phases.push(entries.at(-1)?.toolActivity?.status)
  }
  expect(phases.slice(1)).toEqual(['pending', 'approval', 'pending', 'running', 'failed'])
  const run: AgentRunState = {
    run_id: 'run',
    request: { provider_id: 'p', model_id: 'm', context_id: 'ctx' },
    status: 'running',
    trace: [...events, events[5]!],
  }
  const restored = reconcileRunTranscript(entries.slice(0, 2), run)
  expect(restored.map((entry) => entry.text || entry.toolActivity?.name)).toEqual([
    '检查',
    '检查文件。',
    'read_text_file',
  ])
  expect(restored.at(-1)?.toolActivity?.errorType).toBe('FileNotFoundError')
  expect(reconcileRunTranscript(restored, run)).toEqual(restored)
  expect(
    reconcileRunTranscript(restored, { ...run, trace: events.slice(0, 5), status: 'canceled' }).at(
      -1,
    )?.toolActivity,
  ).toMatchObject({ status: 'pending', notice: '运行已停止，结果尚未确认' })
})

it('recovers pending approval cards even if the connection dropped before their event', () => {
  const run: AgentRunState = {
    run_id: 'run',
    request: { provider_id: 'p', model_id: 'm', context_id: 'ctx' },
    status: 'paused',
    pending_approval_requests: [
      {
        approval_id: 'approval',
        tool_call_id: call.tool_call_id,
        tool_name: 'read_text_file',
        tool_call: call.tool_call,
      },
    ],
  }
  const restored = reconcileRunTranscript([], run)
  expect(restored[0]?.toolActivity).toMatchObject({ status: 'approval', name: 'read_text_file' })
})
