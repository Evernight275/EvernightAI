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
  trace,
  runId,
  pendingApprovals,
  approvalStatuses,
  cancelableRun,
  send,
  retry,
  clear,
  cancel,
  approve,
  deny,
  resume,
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
      :approval-statuses="approvalStatuses"
      :cancelable-run="cancelableRun"
      @retry="retry"
      @clear="clear"
      @cancel="cancel"
      @approve="approve"
      @deny="deny"
      @resume="resume"
    />

    <ChatToolActivity :run="run" :trace="trace" />
    <ChatTranscript :entries="transcript" />
  </main>
</template>
