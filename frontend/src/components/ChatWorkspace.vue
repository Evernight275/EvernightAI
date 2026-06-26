<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Content, Session } from '../api'
import { formatStatus, shortId } from '../format'
import Icon from './Icon.vue'

type ModelOption = {
  value: string
  label: string
}

const props = defineProps<{
  sessions: Session[]
  modelOptions: ModelOption[]
  selectedSessionId: string | null
  messages: Array<Content & { outgoing?: boolean; text: string }>
  title: string
  loading: boolean
  sending: boolean
  creatingSession: boolean
  disabled: boolean
  error: string | null
}>()

const model = defineModel<string>({ required: true })
const modelSelection = defineModel<string>('modelSelection', { required: true })
const modelPickerOpen = ref(false)
const selectedModelLabel = computed(() => (
  props.modelOptions.find((option) => option.value === modelSelection.value)?.label
  || props.modelOptions[0]?.label
  || '选择模型'
))
const emit = defineEmits<{
  select: [session: Session]
  send: [text: string]
  createSession: []
}>()

function submit() {
  const text = model.value.trim()
  if (text !== '') {
    modelPickerOpen.value = false
    emit('send', text)
  }
}

function toggleModelPicker() {
  if (props.sending || props.modelOptions.length === 0) {
    return
  }

  modelPickerOpen.value = !modelPickerOpen.value
}

function selectModel(value: string) {
  modelSelection.value = value
  modelPickerOpen.value = false
}
</script>

<template>
  <section class="chat-workspace" aria-label="聊天工作区">
    <aside class="chat-rail">
      <div class="chat-rail-head">
        <strong>会话</strong>
        <button class="button icon-button" type="button" :disabled="creatingSession" @click="emit('createSession')">
          <Icon name="message-square-plus" />
        </button>
      </div>
      <div class="chat-session-list">
        <button
          v-for="session in sessions"
          :key="session.session_id"
          class="chat-session-button"
          :class="{ 'is-selected': session.session_id === selectedSessionId }"
          type="button"
          @click="emit('select', session)"
        >
          <span>{{ session.title || shortId(session.session_id) }}</span>
          <small>{{ session.model_id || '未指定模型' }}</small>
        </button>
        <div v-if="sessions.length === 0" class="chat-rail-empty">
          暂无会话
        </div>
      </div>
    </aside>

    <div class="chat-main">
      <header class="chat-main-head">
        <div>
          <h2>{{ title }}</h2>
          <p>{{ selectedSessionId ? '当前上下文会被服务端持久化' : '新建或选择一个会话' }}</p>
        </div>
      </header>

      <div class="chat-thread">
        <div v-if="loading" class="chat-thread-message system">
          <strong>系统</strong>
          <p>正在加载上下文...</p>
        </div>
        <div
          v-else
          v-for="(message, index) in messages"
          :key="`${message.role}-${index}`"
          class="chat-thread-message"
          :class="{ assistant: message.role === 'assistant', user: message.role === 'user' }"
        >
          <strong>{{ formatStatus(message.role) }}</strong>
          <p>{{ message.text || '无文本内容' }}</p>
        </div>
      </div>

      <form class="chat-composer" @submit.prevent="submit">
        <div class="chat-input-shell">
          <textarea
            v-model="model"
            rows="4"
            placeholder="给当前会话发送消息"
            :disabled="disabled || sending"
            @focus="modelPickerOpen = false"
            @keydown.enter.exact.prevent="submit"
          ></textarea>
          <div class="chat-input-actions">
            <div class="model-picker" :class="{ 'is-open': modelPickerOpen }">
              <button
                class="model-picker-trigger"
                type="button"
                :disabled="sending || modelOptions.length === 0"
                :aria-expanded="modelPickerOpen"
                aria-haspopup="listbox"
                @click="toggleModelPicker"
              >
                <span>{{ selectedModelLabel }}</span>
                <Icon name="chevron-down" />
              </button>
              <Transition name="model-menu">
                <div v-if="modelPickerOpen" class="model-picker-menu" role="listbox">
                  <button
                  v-for="option in modelOptions"
                  :key="option.value"
                    class="model-picker-option"
                    :class="{ 'is-selected': option.value === modelSelection }"
                    type="button"
                    role="option"
                    :aria-selected="option.value === modelSelection"
                    @click="selectModel(option.value)"
                >
                  {{ option.label }}
                  </button>
                </div>
              </Transition>
            </div>
            <button
              class="chat-send-button"
              type="submit"
              :disabled="disabled || sending || model.trim() === ''"
              :title="sending ? '发送中' : '发送'"
              :aria-label="sending ? '发送中' : '发送'"
            >
              <Icon name="send" />
            </button>
          </div>
        </div>
        <span class="chat-composer-hint">{{ error || 'Enter 发送，Shift+Enter 换行' }}</span>
      </form>
    </div>
  </section>
</template>
