<script setup lang="ts">
import ChatHeader from './ChatHeader.vue'
import ChatRequestForm from './ChatRequestForm.vue'
import ChatRunDetails from './ChatRunDetails.vue'
import ChatTranscript from './ChatTranscript.vue'
import { useChatView } from './chatView'

const {
  workspaceState,
  chatState,
  detailsOpen,
  workspaceIssues,
  providerCatalog,
  toolCatalog,
  busy,
  error,
  transcript,
  hasTranscript,
  run,
  session,
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
  <section class="chat-view">
    <ChatHeader :session="session">
      <ChatRunDetails
        :open="detailsOpen"
        :workspace-state="workspaceState"
        :chat-state="chatState"
        :workspace-issues="workspaceIssues"
        :provider-count="providerCatalog.providers.length"
        :tool-count="toolCatalog.length"
        :error="error"
        :has-transcript="hasTranscript"
        :run="run"
        :trace="trace"
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
    </ChatHeader>

    <div class="chat-view-scroll">
      <div class="chat-content">
        <ChatTranscript :entries="transcript" />
      </div>
    </div>

    <footer class="chat-view-footer">
      <div class="chat-content">
        <ChatRequestForm
          :catalog="providerCatalog"
          :busy="busy"
          :session-ready="session !== null"
          :default-provider-id="session?.provider_id"
          :default-model-id="session?.model_id"
          @submit="send"
        />
      </div>
    </footer>
  </section>
</template>
