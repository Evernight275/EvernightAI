import { apiBase, getApiKey } from './client'
import type { AgentRunRequest, AgentTraceEvent } from './agentRuns'
import type { ToolApprovalDecision } from './tools'

export type WebSocketMessageType =
  | 'hello'
  | 'heartbeat'
  | 'heartbeat_ack'
  | 'agent_trace'
  | 'agent_control'
  | 'tool_approval'
  | 'client_event'
  | 'error'

export type WebSocketAgentControlAction = 'cancel' | 'pause' | 'resume'

export type WebSocketHeartbeat = {
  sequence?: number | null
  sent_at?: string | null
  metadata?: Record<string, unknown>
}

export type WebSocketHello = {
  protocol_version?: string
  connection_id?: string | null
  capabilities?: WebSocketMessageType[]
  metadata?: Record<string, unknown>
}

export type WebSocketError = {
  error_type: string
  error_message: string
  retryable?: boolean
  metadata?: Record<string, unknown>
}

export type WebSocketClientEvent = {
  event_name: string
  payload?: Record<string, unknown>
  metadata?: Record<string, unknown>
}

export type WebSocketTracePayload = {
  sequence?: number
  replayed?: boolean
}

export type WebSocketMessage = {
  message_type: WebSocketMessageType
  message_id?: string | null
  correlation_id?: string | null
  run_id?: string | null
  hello?: WebSocketHello | null
  heartbeat?: WebSocketHeartbeat | null
  client_event?: WebSocketClientEvent | null
  trace_event?: AgentTraceEvent | null
  error?: WebSocketError | null
  payload?: Record<string, unknown>
  metadata?: Record<string, unknown>
}

type AgentRunSocketHandlers = {
  onStatus?: (status: AgentRunSocketStatus) => void
  onTrace?: (runId: string, event: AgentTraceEvent, payload: WebSocketTracePayload, message: WebSocketMessage) => void
  onError?: (error: WebSocketError, message: WebSocketMessage) => void
  onSubscription?: (runId: string, subscribed: boolean, sequence: number) => void
}

export type AgentRunSocketStatus = 'connecting' | 'connected' | 'disconnected'

export class AgentRunSocketClient {
  private socket: WebSocket | null = null
  private reconnectTimer: number | null = null
  private reconnectDelayMs = 1000
  private manuallyClosed = false
  private readonly handlers: AgentRunSocketHandlers
  private readonly subscriptions = new Map<string, number>()
  private readonly pendingMessages: Record<string, unknown>[] = []
  private readonly pendingStartRunIds = new Set<string>()

  constructor(handlers: AgentRunSocketHandlers = {}) {
    this.handlers = handlers
  }

  connect() {
    if (this.socket && this.socket.readyState <= WebSocket.OPEN) {
      return
    }

    this.manuallyClosed = false
    this.emitStatus('connecting')
    const socket = new WebSocket(webSocketUrl(), webSocketProtocols())
    this.socket = socket

    socket.addEventListener('open', () => {
      this.reconnectDelayMs = 1000
      this.emitStatus('connected')
      this.resubscribe(this.pendingStartRunIds)
      this.flushPendingMessages()
      this.pendingStartRunIds.clear()
    })
    socket.addEventListener('message', (event) => this.handleMessage(event))
    socket.addEventListener('close', (event) => {
      if (event.code === 1008) {
        this.manuallyClosed = true
      }
      this.emitStatus('disconnected')
      if (!this.manuallyClosed) {
        this.scheduleReconnect()
      }
    })
    socket.addEventListener('error', () => {
      this.emitStatus('disconnected')
    })
  }

  close() {
    this.manuallyClosed = true
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.socket?.close()
    this.socket = null
    this.pendingMessages.length = 0
    this.pendingStartRunIds.clear()
    this.emitStatus('disconnected')
  }

  startRun(request: AgentRunRequest) {
    const runId = typeof request.metadata?.run_id === 'string' ? request.metadata.run_id : null
    if (runId) {
      this.subscriptions.set(runId, 0)
    }
    const sent = this.send({
      message_type: 'client_event',
      message_id: messageId('start'),
      client_event: {
        event_name: 'agent_run.start',
        payload: request,
      },
    })
    if (!sent && runId) {
      this.pendingStartRunIds.add(runId)
    }
  }

  subscribeRun(runId: string, afterSequence = this.subscriptions.get(runId) || 0) {
    const cursor = Math.max(this.subscriptions.get(runId) || 0, afterSequence)
    this.subscriptions.set(runId, cursor)
    this.sendSubscribe(runId, cursor)
  }

  unsubscribeRun(runId: string) {
    this.subscriptions.delete(runId)
    this.send({
      message_type: 'client_event',
      message_id: messageId('unsubscribe'),
      client_event: {
        event_name: 'agent_run.unsubscribe',
        payload: { run_id: runId },
      },
    })
  }

  controlRun(runId: string, action: WebSocketAgentControlAction, reason?: string) {
    this.send({
      message_type: 'agent_control',
      message_id: messageId(action),
      agent_control: {
        run_id: runId,
        action,
        ...(reason ? { reason } : {}),
      },
    })
  }

  approveTool(runId: string, decision: ToolApprovalDecision) {
    this.send({
      message_type: 'tool_approval',
      message_id: messageId('approval'),
      tool_approval: {
        run_id: runId,
        decision,
      },
    })
  }

  private handleMessage(event: MessageEvent<string>) {
    const message = JSON.parse(event.data) as WebSocketMessage
    if (message.message_type === 'heartbeat') {
      this.send({
        message_type: 'heartbeat_ack',
        correlation_id: message.message_id || undefined,
        heartbeat: message.heartbeat || undefined,
      })
      return
    }
    if (message.message_type === 'agent_trace' && message.run_id && message.trace_event) {
      const payload = tracePayload(message.payload)
      if (payload.sequence !== undefined) {
        this.subscriptions.set(
          message.run_id,
          Math.max(this.subscriptions.get(message.run_id) || 0, payload.sequence),
        )
      }
      this.handlers.onTrace?.(message.run_id, message.trace_event, payload, message)
      return
    }
    if (message.message_type === 'client_event' && message.client_event) {
      this.handleClientEvent(message.client_event)
      return
    }
    if (message.message_type === 'error' && message.error) {
      this.handlers.onError?.(message.error, message)
    }
  }

  private handleClientEvent(event: WebSocketClientEvent) {
    const runId = typeof event.payload?.run_id === 'string' ? event.payload.run_id : null
    if (!runId) {
      return
    }
    if (event.event_name === 'agent_run.subscribed') {
      const sequence = typeof event.payload?.sequence === 'number' ? event.payload.sequence : 0
      const cursor = Math.max(this.subscriptions.get(runId) || 0, sequence)
      this.subscriptions.set(runId, cursor)
      this.handlers.onSubscription?.(runId, true, cursor)
      return
    }
    if (event.event_name === 'agent_run.unsubscribed') {
      this.subscriptions.delete(runId)
      this.handlers.onSubscription?.(runId, false, 0)
    }
  }

  private send(message: Record<string, unknown>): boolean {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      this.pendingMessages.push(message)
      this.connect()
      return false
    }
    this.socket.send(JSON.stringify(message))
    return true
  }

  private sendSubscribe(runId: string, afterSequence: number) {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      this.connect()
      return
    }
    this.socket.send(JSON.stringify({
      message_type: 'client_event',
      message_id: messageId('subscribe'),
      client_event: {
        event_name: 'agent_run.subscribe',
        payload: {
          run_id: runId,
          after_sequence: afterSequence,
        },
      },
    }))
  }

  private resubscribe(excludedRunIds: ReadonlySet<string> = new Set()) {
    for (const [runId, afterSequence] of this.subscriptions.entries()) {
      if (excludedRunIds.has(runId)) {
        continue
      }
      this.sendSubscribe(runId, afterSequence)
    }
  }

  private flushPendingMessages() {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      return
    }
    for (const message of this.pendingMessages.splice(0)) {
      this.socket.send(JSON.stringify(message))
    }
  }

  private scheduleReconnect() {
    if (this.reconnectTimer !== null) {
      return
    }
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null
      this.connect()
    }, this.reconnectDelayMs)
    this.reconnectDelayMs = Math.min(this.reconnectDelayMs * 2, 10_000)
  }

  private emitStatus(status: AgentRunSocketStatus) {
    this.handlers.onStatus?.(status)
  }
}

function webSocketUrl(): string {
  const base = apiBase || window.location.origin
  const url = new URL('/ws', base)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  return url.toString()
}

function webSocketProtocols(): string[] {
  const apiKey = getApiKey()
  if (!apiKey) {
    return ['evernight.realtime']
  }

  return ['evernight.realtime', `evernight.api_key.${base64UrlEncode(apiKey)}`]
}

function base64UrlEncode(value: string): string {
  const bytes = new TextEncoder().encode(value)
  let binary = ''
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte)
  })
  return window.btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function messageId(prefix: string): string {
  if (window.crypto?.randomUUID) {
    return `${prefix}-${window.crypto.randomUUID()}`
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function tracePayload(payload: Record<string, unknown> | undefined): WebSocketTracePayload {
  return {
    sequence: typeof payload?.sequence === 'number' ? payload.sequence : undefined,
    replayed: typeof payload?.replayed === 'boolean' ? payload.replayed : undefined,
  }
}
