<script setup lang="ts">
import { SquarePen, Settings, X, PanelLeftClose, Search, Trash2 } from '@lucide/vue'
import { computed, ref } from 'vue'
import { useDialog } from '../common/dialog'
import type { ChatSidebarItem } from './chatSidebar'
import EmptyValue from '../common/EmptyValue.vue'
import { useChatSidebar, useSidebarDialog } from './chatSidebar'

const props = defineProps<{ open: boolean; collapsed?: boolean }>()
const emit = defineEmits<{ close: []; collapse: [] }>()
const { sessions, newConversation, selectSession, removeSession, deletingId } = useChatSidebar(() => emit('close'))
const { setDialog, onCancel, onBackdropClick, onKeydown } = useSidebarDialog(props, () => emit('close'))
const search = ref('')
const filteredSessions = computed(() => sessions.value.filter(
  (session) => session.title.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase()),
))
const pendingDelete = ref<ChatSidebarItem | null>(null)
const deleteError = ref('')
function closeDelete(): void { if (!deletingId.value) pendingDelete.value = null }
const deleteDialog = useDialog(() => pendingDelete.value !== null, closeDelete)
function requestDelete(session: ChatSidebarItem): void {
  pendingDelete.value = session
  deleteError.value = ''
}
async function confirmDelete(): Promise<void> {
  if (!pendingDelete.value) return
  try {
    await removeSession(pendingDelete.value.id)
    pendingDelete.value = null
  } catch (error) {
    deleteError.value = error instanceof Error ? error.message : '删除失败，请重试'
  }
}
</script>

<template>
  <dialog :ref="setDialog" class="chat-sidebar-dialog" aria-label="会话管理"
    @cancel="onCancel" @click="onBackdropClick" @keydown="onKeydown">
    <aside class="chat-sidebar">
      <header class="chat-sidebar-header">
        <button class="icon-button chat-navigation-close" type="button" aria-label="关闭会话管理"
          title="关闭会话管理" @click="$emit('close')"><X :size="18" aria-hidden="true" /></button>
        <h1 class="chat-sidebar-brand">EvernightAI</h1>
        <button class="icon-button chat-sidebar-collapse" type="button" aria-label="收起侧栏"
          title="收起侧栏" @click="$emit('collapse')"><PanelLeftClose :size="19" aria-hidden="true" /></button>
        <button class="chat-sidebar-new" type="button" :disabled="!!deletingId" @click="newConversation">
          <SquarePen :size="18" aria-hidden="true" />
          新建会话
        </button>
        <label class="chat-sidebar-search">
          <Search :size="17" aria-hidden="true" />
          <input v-model="search" type="search" placeholder="搜索会话" aria-label="搜索会话" />
        </label>
      </header>

      <section class="chat-sidebar-sessions" aria-label="会话列表">
        <p class="chat-sidebar-label">你的会话</p>
        <EmptyValue v-if="sessions.length === 0" label="没有会话" />
        <EmptyValue v-else-if="filteredSessions.length === 0" label="没有找到匹配的会话" />
        <ul v-else class="chat-sidebar-list">
          <li v-for="session in filteredSessions" :key="session.id">
            <button
              class="chat-session-button"
              type="button"
              :aria-current="session.active ? 'true' : undefined"
              :disabled="!!deletingId"
              @click="selectSession(session.id)"
            >
              <span class="chat-session-title">{{ session.title }}</span>
            </button>
            <button class="icon-button chat-session-delete" type="button" :disabled="!!deletingId"
              :aria-label="`删除会话：${session.title}`" title="删除会话" @click="requestDelete(session)">
              <Trash2 :size="15" aria-hidden="true" />
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
  <dialog :ref="deleteDialog.setDialog" class="chat-confirm-dialog" aria-labelledby="delete-session-title"
    @cancel="deleteDialog.onCancel" @click="deleteDialog.onBackdropClick" @keydown="deleteDialog.onKeydown">
    <h2 id="delete-session-title">删除这个会话？</h2>
    <p>「{{ pendingDelete?.title }}」将从会话列表中永久删除。</p>
    <p v-if="deleteError" class="chat-status-error" role="alert">{{ deleteError }}</p>
    <div class="chat-confirm-actions">
      <button type="button" :disabled="!!deletingId" autofocus @click="closeDelete">取消</button>
      <button class="chat-delete-confirm" type="button" :disabled="!!deletingId" @click="confirmDelete">
        {{ deletingId ? '正在删除…' : '删除' }}
      </button>
    </div>
  </dialog>
</template>
