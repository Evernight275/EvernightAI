<script setup lang="ts">
import { Menu, PanelRight, Pencil } from '@lucide/vue'
import { ref } from 'vue'
import { getSession, replaceSession } from '../../api'
import { chatActor } from '../../state/chatMachine'
import { workspaceActor } from '../../state/workspaceMachine'
import { useDialog } from '../common/dialog'
import { useChatHeader, type ChatHeaderProps } from './chatHeader'

const props = defineProps<ChatHeaderProps>()
defineEmits<{ details: []; navigation: [] }>()
const { title, stateLabel } = useChatHeader(props)
const editing = ref(false)
const draft = ref('')
const busy = ref(false)
const error = ref('')
const dialog = useDialog(() => editing.value, () => { if (!busy.value) editing.value = false })
async function save() {
  if (!props.session || busy.value) return
  const id = props.session.session_id
  busy.value = true; error.value = ''
  try {
    const current = await getSession(id)
    const updated = await replaceSession(id, { ...current, title: draft.value.trim() })
    chatActor.send({ type: 'SESSION_UPDATED', session: updated }); workspaceActor.send({ type: 'REFRESH' }); editing.value = false
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '保存失败' }
  finally { busy.value = false }
}
</script>

<template>
  <header class="chat-view-header">
    <div class="chat-header-content">
      <div class="chat-header-main">
        <button class="icon-button chat-navigation-toggle" type="button"
          aria-label="会话管理" title="会话管理" @click="$emit('navigation')">
          <Menu :size="18" aria-hidden="true" />
        </button>
        <div class="chat-header-heading">
          <h1 class="chat-header-title">{{ title }}</h1>
          <button v-if="session" class="icon-button" type="button" aria-label="编辑会话标题" @click="draft = session.title || ''; error = ''; editing = true"><Pencil :size="15" aria-hidden="true" /></button>
          <p class="chat-header-status" :class="{ 'sr-only': state === 'idle' }" role="status">{{ stateLabel }}</p>
        </div>
        <button class="icon-button" type="button" aria-label="运行详情"
          title="运行详情" aria-haspopup="dialog" :aria-expanded="detailsOpen"
          aria-controls="chat-run-details" @click="$emit('details')">
          <PanelRight :size="18" aria-hidden="true" />
        </button>
      </div>
    </div>
  </header>
  <dialog :ref="dialog.setDialog" class="chat-confirm-dialog" aria-label="编辑会话" @cancel="dialog.onCancel" @click="dialog.onBackdropClick" @keydown="dialog.onKeydown">
    <form class="settings-form" @submit.prevent="save"><label>会话标题<input v-model="draft" required :disabled="busy" /></label><p v-if="error" role="alert">{{ error }}</p><div class="chat-confirm-actions"><button type="button" :disabled="busy" @click="editing = false">取消</button><button :disabled="busy || !draft.trim()">保存标题</button></div></form>
  </dialog>
</template>
