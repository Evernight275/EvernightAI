<script setup lang="ts">
import ChatHeader from './ChatHeader.vue'
import ChatRequestForm from './ChatRequestForm.vue'
import ChatRequestStatus from './ChatRequestStatus.vue'
import ChatRunDetails from './ChatRunDetails.vue'
import ChatTranscript from './ChatTranscript.vue'
import { useChatView } from './chatView'

defineEmits<{ navigation: [] }>()

const {
  workspaceState,
  chatState,
  detailsOpen,
  openDetails,
  closeDetails,
  workspaceNotice,
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
    <ChatHeader :session="session" :state="chatState" :details-open="detailsOpen"
      @details="openDetails" @navigation="$emit('navigation')" />

    <div class="chat-view-scroll">
      <div class="chat-content">
        <ChatTranscript :entries="transcript" />
      </div>
    </div>

    <footer class="chat-view-footer">
      <div class="chat-content">
        <ChatRequestStatus :state="chatState" :error="error" :workspace-notice="workspaceNotice"
          :pending-approvals="pendingApprovals" :approval-statuses="approvalStatuses"
          @retry="retry" @resume="resume" @approve="approve" @deny="deny" @details="openDetails" />
        <ChatRequestForm
          :catalog="providerCatalog"
          :busy="busy"
          :state="chatState"
          :can-stop="cancelableRun"
          :session-ready="session !== null"
          :default-provider-id="session?.provider_id"
          :default-model-id="session?.model_id"
          @submit="send"
          @cancel="cancel"
        />
      </div>
    </footer>
    <ChatRunDetails :open="detailsOpen" :workspace-state="workspaceState" :chat-state="chatState"
      :workspace-issues="workspaceIssues" :provider-count="providerCatalog.providers.length"
      :tool-count="toolCatalog.length" :error="error" :has-transcript="hasTranscript" :busy="busy"
      :run="run" :trace="trace" :run-id="runId" :pending-approvals="pendingApprovals"
      @clear="clear" @close="closeDetails" />
  </section>
</template>
