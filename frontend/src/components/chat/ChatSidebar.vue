<script setup lang="ts">
import { Plus, Settings, X } from '@lucide/vue'
import EmptyValue from '../common/EmptyValue.vue'
import { useChatSidebar, useSidebarDialog } from './chatSidebar'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()
const { sessions, newConversation, selectSession } = useChatSidebar(() => emit('close'))
const { setDialog, onCancel, onBackdropClick, onKeydown } = useSidebarDialog(props, () => emit('close'))
</script>

<template>
  <dialog :ref="setDialog" class="chat-sidebar-dialog" aria-label="会话管理"
    @cancel="onCancel" @click="onBackdropClick" @keydown="onKeydown">
    <aside class="chat-sidebar">
      <header class="chat-sidebar-header">
        <button class="icon-button chat-navigation-close" type="button" aria-label="关闭会话管理"
          title="关闭会话管理" @click="$emit('close')"><X :size="18" aria-hidden="true" /></button>
        <h1 class="chat-sidebar-brand">EvernightAI</h1>
        <p class="chat-sidebar-label">会话</p>
        <button class="chat-sidebar-new" type="button" @click="newConversation">
          <Plus :size="16" aria-hidden="true" />
          新建会话
        </button>
      </header>

      <section class="chat-sidebar-sessions" aria-label="会话列表">
        <EmptyValue v-if="sessions.length === 0" label="没有会话" />
        <ul v-else class="chat-sidebar-list">
          <li v-for="session in sessions" :key="session.id">
            <button
              class="chat-session-button"
              type="button"
              :aria-current="session.active ? 'true' : undefined"
              @click="selectSession(session.id)"
            >
              <span class="chat-session-title">{{ session.title }}</span>
              <small class="chat-session-status">{{ session.status }}</small>
            </button>
          </li>
        </ul>
      </section>

      <footer class="chat-sidebar-settings">
        <a href="/">
          <Settings :size="16" aria-hidden="true" />
          设置
        </a>
      </footer>
    </aside>
  </dialog>
</template>
