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
