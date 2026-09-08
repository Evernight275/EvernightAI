<script setup lang="ts">
import { computed, onUnmounted, shallowRef } from 'vue'
import { workspaceActor } from '../../state/workspaceMachine'
import ApiKeySettings from '../settings/ApiKeySettings.vue'
import WorkspaceContents from './WorkspaceContents.vue'
import WorkspaceIssues from './WorkspaceIssues.vue'
import WorkspaceStatus from './WorkspaceStatus.vue'

const snapshot = shallowRef(workspaceActor.getSnapshot())
const subscription = workspaceActor.subscribe((nextSnapshot) => {
  snapshot.value = nextSnapshot
})

const state = computed(() => String(snapshot.value.value))
const context = computed(() => snapshot.value.context)

onUnmounted(() => subscription.unsubscribe())

function refresh(): void {
  workspaceActor.send({ type: 'REFRESH' })
}
</script>

<template>
  <main class="settings-page">
    <header class="settings-page-header">
      <div>
        <p class="settings-eyebrow">EvernightAI</p>
        <h1>设置</h1>
        <p class="settings-page-description">管理连接凭证与工作区状态。</p>
      </div>
      <a class="settings-back-link" href="/chat.html">返回 Chat</a>
    </header>

    <ApiKeySettings />

    <WorkspaceStatus
      :state="state"
      :loaded-at="context.workspace.loadedAt"
      :connection-error="context.connectionError"
      @refresh="refresh"
    />

    <WorkspaceIssues :issues="context.issues" />

    <WorkspaceContents
      v-if="context.workspace.loadedAt"
      :workspace="context.workspace"
    />
  </main>
</template>
