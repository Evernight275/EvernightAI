<script setup lang="ts">
import type { Content } from '../api'
import { formatStatus } from '../format'
import Icon from './Icon.vue'

defineProps<{
  messages: Array<Content & { outgoing?: boolean; text: string }>
  title: string
  loading: boolean
  sending: boolean
  creatingSession: boolean
  disabled: boolean
  error: string | null
}>()

const model = defineModel<string>({ required: true })
const emit = defineEmits<{
  send: [text: string]
  createSession: []
}>()

function submit() {
  const text = model.value.trim()
  if (text !== '') {
    emit('send', text)
  }
}
</script>

<template>
  <section class="panel chat-panel">
    <div class="panel-head">
      <h2><Icon name="message-square" /><span>聊天</span></h2>
      <div class="panel-head-actions">
        <span>{{ title }}</span>
        <button class="button compact-button" type="button" :disabled="creatingSession" @click="emit('createSession')">
          <Icon name="message-square-plus" />
          <span>{{ creatingSession ? '创建中' : '新建' }}</span>
        </button>
      </div>
    </div>
    <div class="chat-stream">
      <div v-if="loading" class="chat-bubble">
        <strong>系统</strong>
        <span>正在加载上下文...</span>
      </div>
      <div
        v-else
        v-for="(message, index) in messages"
        :key="`${message.role}-${index}`"
        class="chat-bubble"
        :class="{ outgoing: message.outgoing || message.role === 'assistant' }"
      >
        <strong>{{ formatStatus(message.role) }}</strong>
        <span>{{ message.text || '无文本内容' }}</span>
      </div>
    </div>
    <form class="chat-form" @submit.prevent="submit">
      <textarea
        v-model="model"
        class="chat-input"
        rows="3"
        placeholder="输入消息"
        :disabled="disabled || sending"
        @keydown.enter.exact.prevent="submit"
      ></textarea>
      <div class="chat-actions">
        <span class="chat-error">{{ error || '' }}</span>
        <button class="button" type="submit" :disabled="disabled || sending || model.trim() === ''">
          <Icon name="send" />
          <span>{{ sending ? '发送中' : '发送' }}</span>
        </button>
      </div>
    </form>
  </section>
</template>
