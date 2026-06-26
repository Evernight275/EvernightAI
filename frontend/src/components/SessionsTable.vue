<script setup lang="ts">
import type { Session } from '../api'
import { formatStatus, formatTime, shortId } from '../format'
import Icon from './Icon.vue'

defineProps<{
  sessions: Session[]
  selectedSessionId: string | null
}>()

const emit = defineEmits<{
  select: [session: Session]
}>()
</script>

<template>
  <section class="table-wrap" aria-label="最近会话">
    <div class="panel-head table-head">
      <h2><Icon name="table-2" /><span>最近会话</span></h2>
      <span>{{ sessions.length }} 条</span>
    </div>
    <table>
      <thead>
        <tr>
          <th>会话</th>
          <th>Agent</th>
          <th>触发词</th>
          <th>状态</th>
          <th>延迟</th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="sessions.length === 0">
          <td>暂无会话</td>
          <td>-</td>
          <td>-</td>
          <td><span class="tag">空</span></td>
          <td>-</td>
        </tr>
        <tr
          v-for="session in sessions"
          v-else
          :key="session.session_id"
          class="session-row"
          :class="{ 'is-selected': session.session_id === selectedSessionId }"
          tabindex="0"
          @click="emit('select', session)"
          @keydown.enter="emit('select', session)"
        >
          <td>{{ session.title || shortId(session.session_id) }}</td>
          <td>{{ session.provider_id || '未绑定' }}</td>
          <td>{{ session.model_id || '未指定' }}</td>
          <td><span class="tag">{{ formatStatus(session.status) }}</span></td>
          <td>{{ formatTime(session.updated_at || session.created_at) }}</td>
        </tr>
      </tbody>
    </table>
  </section>
</template>
