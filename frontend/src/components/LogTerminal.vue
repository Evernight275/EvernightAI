<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { clearLogs, listLogs, type Log } from '../api'
import Icon from './Icon.vue'

const logs = ref<Log[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const autoRefresh = ref(true)
const updatedAt = ref('')
const terminalRef = ref<HTMLElement | null>(null)
let refreshTimer: number | undefined

const lastLogSequence = computed(() => logs.value.at(-1)?.sequence ?? undefined)
const hasLogs = computed(() => logs.value.length > 0)

async function refreshLogs({ incremental = false } = {}) {
  if (loading.value) {
    return
  }

  loading.value = true
  error.value = null
  try {
    const nextLogs = await listLogs({
      limit: incremental && lastLogSequence.value !== undefined ? 500 : 300,
      after: incremental ? lastLogSequence.value : undefined,
    })
    logs.value = incremental ? mergeLogs(logs.value, nextLogs) : nextLogs
    updatedAt.value = new Date().toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
    await scrollToBottom()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '日志读取失败'
  } finally {
    loading.value = false
  }
}

async function clearVisibleLogs() {
  loading.value = true
  error.value = null
  try {
    await clearLogs()
    logs.value = []
    updatedAt.value = new Date().toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '日志清理失败'
  } finally {
    loading.value = false
  }
}

function mergeLogs(current: Log[], incoming: Log[]): Log[] {
  const entries = new Map<number, Log>()
  current.forEach((entry, index) => entries.set(entry.sequence ?? index + 1, entry))
  incoming.forEach((entry, index) => entries.set(entry.sequence ?? current.length + index + 1, entry))
  return [...entries.values()]
    .sort((left, right) => (left.sequence ?? 0) - (right.sequence ?? 0))
    .slice(-500)
}

function formatTimestamp(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }

  return date.toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function formatSource(entry: Log): string {
  const metadata = entry.metadata || {}
  const location = [
    typeof metadata.module === 'string' ? metadata.module : '',
    typeof metadata.function === 'string' ? metadata.function : '',
  ].filter(Boolean).join('.')
  const line = typeof metadata.line === 'number' ? `:${metadata.line}` : ''
  return location ? `${entry.source} ${location}${line}` : `${entry.source}${line}`
}

async function scrollToBottom() {
  await nextTick()
  const terminal = terminalRef.value
  if (!terminal) {
    return
  }

  terminal.scrollTop = terminal.scrollHeight
}

function syncAutoRefresh() {
  if (refreshTimer !== undefined) {
    window.clearInterval(refreshTimer)
    refreshTimer = undefined
  }
  if (autoRefresh.value) {
    refreshTimer = window.setInterval(() => {
      void refreshLogs({ incremental: true })
    }, 2500)
  }
}

onMounted(async () => {
  await refreshLogs()
  syncAutoRefresh()
})

onBeforeUnmount(() => {
  if (refreshTimer !== undefined) {
    window.clearInterval(refreshTimer)
  }
})

watch(autoRefresh, syncAutoRefresh)
</script>

<template>
  <section class="log-terminal-shell" aria-label="日志终端">
    <div class="log-terminal-head">
      <div>
        <h2><Icon name="terminal" /><span>日志终端</span></h2>
        <p>{{ updatedAt ? `最后刷新 ${updatedAt}` : '等待日志数据' }}</p>
      </div>
      <div class="log-terminal-actions">
        <label class="log-terminal-toggle">
          <input v-model="autoRefresh" type="checkbox">
          <span>自动刷新</span>
        </label>
        <button class="button compact-button" type="button" :disabled="loading" @click="refreshLogs()">
          <Icon name="rotate-ccw" />
          <span>{{ loading ? '刷新中' : '刷新' }}</span>
        </button>
        <button class="button compact-button" type="button" :disabled="loading || !hasLogs" @click="clearVisibleLogs">
          <Icon name="trash-2" />
          <span>清空</span>
        </button>
      </div>
    </div>

    <div ref="terminalRef" class="log-terminal">
      <div v-if="error" class="log-terminal-line error">
        <span class="log-time">error</span>
        <span class="log-level">[error]</span>
        <span class="log-message">{{ error }}</span>
      </div>
      <div v-else-if="logs.length === 0" class="log-terminal-empty">
        <span>$</span>
        <span>{{ loading ? 'waiting for logs...' : 'no logs captured yet' }}</span>
      </div>
      <div
        v-for="entry in logs"
        v-else
        :key="entry.sequence ?? `${entry.source}-${entry.message}`"
        class="log-terminal-line"
        :class="entry.level"
      >
        <span class="log-time">{{ formatTimestamp(entry.occurred_at || '') }}</span>
        <span class="log-level">[{{ entry.level }}]</span>
        <span class="log-source">{{ formatSource(entry) }}</span>
        <span class="log-message">{{ entry.message }}</span>
      </div>
    </div>
  </section>
</template>
