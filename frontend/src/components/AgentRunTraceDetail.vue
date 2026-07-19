<script setup lang="ts">
import { computed } from 'vue'
import type {
  AgentRunState,
  AgentTraceEvent,
  AgentRunSocketStatus,
  ToolApprovalRequest,
  ToolCall,
  ToolCallResult,
} from '../api'
import { formatStatus } from '../format'
import Icon from './Icon.vue'

const props = defineProps<{
  run: AgentRunState | null
  socketStatus?: AgentRunSocketStatus
}>()

const emit = defineEmits<{
  pause: [run: AgentRunState]
  cancel: [run: AgentRunState]
  resume: [run: AgentRunState]
}>()

type TraceTone = 'primary' | 'success' | 'warning' | 'danger'
const previewLimit = 120

const traceEvents = computed(() => props.run?.trace || [])
const toolEvents = computed(() => traceEvents.value.filter((event) => event.tool_call || event.tool_result || event.approval_request))
const requestTools = computed(() => props.run?.request.tools || [])
const pendingApprovals = computed(() => props.run?.pending_approval_requests || [])
const pendingToolCalls = computed(() => props.run?.pending_tool_calls || [])
const realtimeStatus = computed(() => props.socketStatus || 'disconnected')
const realtimeReady = computed(() => realtimeStatus.value === 'connected')
const isRunning = computed(() => props.run?.status === 'running')
const isPaused = computed(() => props.run?.status === 'paused')
const hasRunControls = computed(() => isRunning.value || isPaused.value)
const canPause = computed(() => isRunning.value && realtimeReady.value)
const canCancel = computed(() => hasRunControls.value && realtimeReady.value)
const canResume = computed(() => isPaused.value && realtimeReady.value)

const traceCounts = computed(() => {
  const counts = {
    toolCalls: 0,
    toolSuccess: 0,
    toolFailure: 0,
    approvals: 0,
  }

  for (const event of traceEvents.value) {
    if (event.tool_call || event.event_type === 'tool_completed' || event.event_type === 'tool_failed') {
      counts.toolCalls += 1
    }
    if (event.event_type === 'tool_completed') {
      counts.toolSuccess += 1
    }
    if (event.event_type === 'tool_failed') {
      counts.toolFailure += 1
    }
    if (event.approval_request || event.event_type === 'tool_approval_requested') {
      counts.approvals += 1
    }
  }

  return counts
})

function traceTone(event: AgentTraceEvent): TraceTone {
  if (event.event_type === 'tool_failed' || event.event_type === 'run_paused') {
    return 'danger'
  }
  if (event.event_type === 'tool_approval_requested' || event.event_type === 'tool_approval_decided') {
    return 'warning'
  }
  if (event.event_type === 'tool_completed' || event.event_type === 'run_stopped') {
    return 'success'
  }

  return 'primary'
}

function statusTone(status: string | undefined): TraceTone {
  if (status === 'failed') {
    return 'danger'
  }
  if (status === 'canceled') {
    return 'danger'
  }
  if (status === 'paused') {
    return 'warning'
  }
  if (status === 'finished') {
    return 'success'
  }

  return 'primary'
}

function realtimeLabel(status: AgentRunSocketStatus): string {
  if (status === 'connected') {
    return 'WS 已连接'
  }
  if (status === 'connecting') {
    return 'WS 连接中'
  }

  return 'WS 未连接'
}

function formatEventType(eventType: string): string {
  return eventType
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function toolName(event: AgentTraceEvent): string {
  return (
    event.approval_request?.tool_name
    || toolCallName(event.tool_call)
    || toolResultName(event.tool_result)
    || '无工具'
  )
}

function toolCallName(toolCall: ToolCall | null | undefined): string | null {
  const name = toolCall?.tool_call?.name
  return typeof name === 'string' && name ? name : null
}

function toolResultName(toolResult: ToolCallResult | null | undefined): string | null {
  const name = toolResult?.tool_call_result?.tool_name
  return typeof name === 'string' && name ? name : null
}

function callArguments(toolCall: ToolCall | null | undefined): string {
  const args = toolCall?.tool_call?.arguments
  if (args === undefined || args === null) {
    return '{}'
  }

  return formatJson(args)
}

function callArgumentsPreview(toolCall: ToolCall | null | undefined): string {
  const args = toolCall?.tool_call?.arguments
  if (args === undefined || args === null) {
    return '无参数'
  }

  return compactJson(args)
}

function resultPreview(toolResult: ToolCallResult | null | undefined): string {
  if (!toolResult) {
    return ''
  }

  return formatJson(toolResult.tool_call_result)
}

function resultSummary(toolResult: ToolCallResult | null | undefined): string {
  if (!toolResult) {
    return '无结果'
  }

  return compactJson(toolResult.tool_call_result)
}

function approvalLabel(request: ToolApprovalRequest): string {
  const permissions = request.permissions?.join(', ') || '无特殊权限'
  return `${request.safety_level || 'safe'} · ${permissions}`
}

function formatJson(value: unknown): string {
  if (typeof value === 'string') {
    return value
  }

  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function compactJson(value: unknown): string {
  const text = typeof value === 'string' ? value : stringifyCompact(value)
  return truncateText(text.replace(/\s+/g, ' ').trim() || '-')
}

function stringifyCompact(value: unknown): string {
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function truncateText(value: string): string {
  if (value.length <= previewLimit) {
    return value
  }

  return `${value.slice(0, previewLimit - 1)}...`
}

function shortId(id: string | undefined): string {
  if (!id) {
    return '-'
  }

  return id.length > 18 ? `${id.slice(0, 8)}...${id.slice(-6)}` : id
}
</script>

<template>
  <section class="run-detail panel" aria-label="运行详情">
    <div v-if="!run" class="run-detail-empty">
      <Icon name="activity" />
      <strong>选择一个 run 查看 trace</strong>
      <span>这里会显示 provider、工具调用、审批和错误细节</span>
    </div>

    <template v-else>
      <div class="run-detail-head">
        <div>
          <h2>{{ shortId(run.run_id) }}</h2>
          <p>{{ run.request.provider_id }} · {{ run.request.model_id }}</p>
        </div>
        <div class="run-detail-actions">
          <span class="tag" :class="statusTone(run.status)">{{ formatStatus(run.status) }}</span>
          <span class="tag" :class="realtimeReady ? 'success' : 'warning'">{{ realtimeLabel(realtimeStatus) }}</span>
          <div v-if="hasRunControls" class="run-control-group" aria-label="运行控制">
            <button
              v-if="isRunning"
              class="button compact-button icon-button"
              type="button"
              :disabled="!canPause"
              title="暂停"
              aria-label="暂停"
              @click="emit('pause', run)"
            >
              <Icon name="pause" />
            </button>
            <button
              v-if="isPaused"
              class="button compact-button icon-button"
              type="button"
              :disabled="!canResume"
              title="继续"
              aria-label="继续"
              @click="emit('resume', run)"
            >
              <Icon name="play" />
            </button>
            <button
              class="button compact-button icon-button danger"
              type="button"
              :disabled="!canCancel"
              title="取消"
              aria-label="取消"
              @click="emit('cancel', run)"
            >
              <Icon name="x" />
            </button>
          </div>
        </div>
      </div>

      <div class="run-detail-metrics">
        <div>
          <span>Tool rounds</span>
          <strong>{{ run.tool_rounds_used ?? 0 }} / {{ run.request.max_tool_rounds ?? 0 }}</strong>
        </div>
        <div>
          <span>Tool events</span>
          <strong>{{ traceCounts.toolCalls }}</strong>
        </div>
        <div>
          <span>Success / failure</span>
          <strong>{{ traceCounts.toolSuccess }} / {{ traceCounts.toolFailure }}</strong>
        </div>
        <div>
          <span>Approvals</span>
          <strong>{{ traceCounts.approvals }}</strong>
        </div>
      </div>

      <div class="run-detail-grid">
        <section class="run-detail-card">
          <div class="run-detail-card-head">
            <h3><Icon name="bot" /><span>Provider</span></h3>
            <span class="tag primary">{{ run.stop_reason || 'running' }}</span>
          </div>
          <dl class="run-facts">
            <div>
              <dt>Provider</dt>
              <dd>{{ run.request.provider_id }}</dd>
            </div>
            <div>
              <dt>Model</dt>
              <dd>{{ run.request.model_id }}</dd>
            </div>
            <div>
              <dt>Context</dt>
              <dd>{{ shortId(run.request.context_id) }}</dd>
            </div>
            <div>
              <dt>Remaining</dt>
              <dd>{{ run.remaining_tool_rounds ?? 0 }}</dd>
            </div>
          </dl>
        </section>

        <section class="run-detail-card">
          <div class="run-detail-card-head">
            <h3><Icon name="wrench" /><span>Tools</span></h3>
            <span class="tag">{{ requestTools.length }} 个</span>
          </div>
          <div v-if="requestTools.length === 0" class="run-muted">本次请求未携带工具定义</div>
          <ul v-else class="run-tool-list">
            <li v-for="tool in requestTools" :key="tool.name">
              <code :title="tool.name">{{ tool.name }}</code>
            </li>
          </ul>
        </section>
      </div>

      <section v-if="pendingApprovals.length > 0" class="run-detail-card">
        <div class="run-detail-card-head">
          <h3><Icon name="shield-check" /><span>Pending approvals</span></h3>
          <span class="tag warning">{{ pendingApprovals.length }} 个</span>
        </div>
        <div class="run-approval-list">
          <article v-for="approval in pendingApprovals" :key="approval.approval_id" class="run-approval">
            <strong>{{ approval.tool_name }}</strong>
            <span>{{ approvalLabel(approval) }}</span>
            <p v-if="approval.reason">{{ approval.reason }}</p>
          </article>
        </div>
      </section>

      <section v-if="pendingToolCalls.length > 0" class="run-detail-card">
        <div class="run-detail-card-head">
          <h3><Icon name="clock" /><span>Pending tool calls</span></h3>
          <span class="tag warning">{{ pendingToolCalls.length }} 个</span>
        </div>
        <div class="run-call-list">
          <article v-for="call in pendingToolCalls" :key="call.tool_call_id" class="run-call">
            <strong>{{ toolCallName(call) || '未知工具' }}</strong>
            <details class="run-json-detail">
              <summary>
                <span>参数</span>
                <code>{{ callArgumentsPreview(call) }}</code>
              </summary>
              <pre><code>{{ callArguments(call) }}</code></pre>
            </details>
          </article>
        </div>
      </section>

      <section class="run-detail-card">
        <div class="run-detail-card-head">
          <h3><Icon name="activity" /><span>Trace timeline</span></h3>
          <span class="tag">{{ traceEvents.length }} 条</span>
        </div>
        <div v-if="traceEvents.length === 0" class="run-muted">暂无 trace 事件</div>
        <ol v-else class="run-trace-list">
          <li
            v-for="(event, index) in traceEvents"
            :key="`${event.event_type}-${index}`"
            class="run-trace-item"
            :class="`is-${traceTone(event)}`"
          >
            <span class="run-trace-dot"></span>
            <div class="run-trace-body">
              <div class="run-trace-title">
                <strong>{{ formatEventType(event.event_type) }}</strong>
                <span v-if="event.step_type">{{ event.step_type }}</span>
              </div>
              <p v-if="event.summary">{{ event.summary }}</p>
              <p v-else-if="event.error_message">{{ event.error_message }}</p>
              <div v-if="event.tool_call || event.tool_result || event.approval_request" class="run-trace-tool">
                <span class="tag">{{ toolName(event) }}</span>
                <details v-if="event.tool_call" class="run-json-detail">
                  <summary>
                    <span>参数</span>
                    <code>{{ callArgumentsPreview(event.tool_call) }}</code>
                  </summary>
                  <pre><code>{{ callArguments(event.tool_call) }}</code></pre>
                </details>
                <details v-if="event.tool_result" class="run-json-detail">
                  <summary>
                    <span>结果</span>
                    <code>{{ resultSummary(event.tool_result) }}</code>
                  </summary>
                  <pre><code>{{ resultPreview(event.tool_result) }}</code></pre>
                </details>
              </div>
            </div>
          </li>
        </ol>
      </section>

      <section v-if="toolEvents.length > 0" class="run-detail-card">
        <div class="run-detail-card-head">
          <h3><Icon name="terminal" /><span>Tool trace</span></h3>
          <span class="tag">{{ toolEvents.length }} 条</span>
        </div>
        <div class="run-call-list">
          <article
            v-for="(event, index) in toolEvents"
            :key="`${event.event_type}-${index}`"
            class="run-call"
          >
            <div class="run-call-head">
              <strong>{{ toolName(event) }}</strong>
              <span class="tag" :class="traceTone(event)">{{ event.event_type }}</span>
            </div>
            <details v-if="event.tool_call" class="run-json-detail">
              <summary>
                <span>参数</span>
                <code>{{ callArgumentsPreview(event.tool_call) }}</code>
              </summary>
              <pre><code>{{ callArguments(event.tool_call) }}</code></pre>
            </details>
            <details v-if="event.tool_result" class="run-json-detail">
              <summary>
                <span>结果</span>
                <code>{{ resultSummary(event.tool_result) }}</code>
              </summary>
              <pre><code>{{ resultPreview(event.tool_result) }}</code></pre>
            </details>
            <p v-if="event.error_message">{{ event.error_message }}</p>
          </article>
        </div>
      </section>
    </template>
  </section>
</template>
