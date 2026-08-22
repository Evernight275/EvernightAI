<script setup lang="ts">
import ChatPrerequisites from './ChatPrerequisites.vue'
import ChatRequestForm from './ChatRequestForm.vue'
import ChatRequestStatus from './ChatRequestStatus.vue'
import ChatToolActivity from './ChatToolActivity.vue'
import ChatTranscript from './ChatTranscript.vue'
import { useChatView } from './chatView'

const {
  workspaceState,
  chatState,
  workspaceIssues,
  providerCatalog,
  toolCatalog,
  busy,
  error,
  transcript,
  hasTranscript,
  run,
  runId,
  pendingApprovals,
  send,
  retry,
  clear,
  approve,
  deny,
} = useChatView()
</script>

<template>
  <main>
    <h1>EvernightAI Chat</h1>
    <p><a href="/">返回 Workspace</a></p>

    <ChatPrerequisites
      :state="workspaceState"
      :provider-count="providerCatalog.providers.length"
      :tool-count="toolCatalog.length"
      :issues="workspaceIssues"
    />

    <ChatRequestForm
      :catalog="providerCatalog"
      :busy="busy"
      @submit="send"
    />

    <ChatRequestStatus
      :state="chatState"
      :error="error"
      :has-transcript="hasTranscript"
      :run-id="runId"
      :pending-approvals="pendingApprovals"
      @retry="retry"
      @clear="clear"
      @approve="approve"
      @deny="deny"
    />

    <ChatToolActivity :run="run" />
    <ChatTranscript :entries="transcript" />
  </main>
</template>
