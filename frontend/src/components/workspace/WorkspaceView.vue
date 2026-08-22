<script setup lang="ts">
import { computed, onUnmounted, shallowRef } from 'vue'
import { workspaceActor } from '../../state/workspaceMachine'
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
  <main>
    <h1>EvernightAI</h1>
    <p><a href="/chat.html">打开 Chat</a></p>

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
