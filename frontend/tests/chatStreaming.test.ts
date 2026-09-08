import { describe, expect, it } from 'vitest'
import { applyChatTrace, completeStreamedResponse, type ChatTranscriptEntry } from '../src/domain/chat'
import type { ChatResponse } from '../src/api'

const response = (text: string): ChatResponse => ({
  model_id: 'model', message: { role: 'assistant', content: [{ type: 'text', text }] },
})

describe('streamed transcript', () => {
  it('separates tool rounds and keeps final reconciliation idempotent', () => {
    let entries: ChatTranscriptEntry[] = []
    entries = applyChatTrace(entries, { event_type: 'chat_delta', text_delta: 'Checking files.' }, 'run')
    entries = applyChatTrace(entries, { event_type: 'chat_completed', response: response('Checking files.') }, 'run')
    entries = applyChatTrace(entries, { event_type: 'tool_completed' }, 'run')
    entries = applyChatTrace(entries, { event_type: 'chat_delta', text_delta: 'The answer' }, 'run')
    entries = applyChatTrace(entries, { event_type: 'chat_delta', text_delta: ' is 42.' }, 'run')
    entries = completeStreamedResponse(entries, response('The answer is 42.'), 'run')
    entries = completeStreamedResponse(entries, response('The answer is 42.'), 'run')
    expect(entries.map((entry) => entry.text)).toEqual(['Checking files.', 'The answer is 42.'])
  })

  it('ignores nontext events and distinguishes retries from the interrupted run', () => {
    let entries = applyChatTrace([], { event_type: 'chat_completed', response: response('') }, 'run')
    expect(entries).toEqual([])
    entries = applyChatTrace(entries, { event_type: 'chat_delta', text_delta: 'partial' }, 'run')
    entries = applyChatTrace(entries, { event_type: 'chat_delta', text_delta: 'new answer' }, 'retry')
    expect(entries.map((entry) => entry.text)).toEqual(['partial', 'new answer'])
  })
})
