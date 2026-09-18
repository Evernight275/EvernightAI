<script setup lang="ts">
import ChatHeader from './ChatHeader.vue'
import ChatRequestForm from './ChatRequestForm.vue'
import ChatRequestStatus from './ChatRequestStatus.vue'
import ChatRunDetails from './ChatRunDetails.vue'
import ChatTranscript from './ChatTranscript.vue'
import { useChatView } from './chatView'

defineEmits<{ navigation: [] }>()

const {
  skills,
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
  <section class="chat-view" :class="{ 'chat-view--empty': !hasTranscript }">
    <ChatHeader :session="session" :state="chatState" :details-open="detailsOpen"
      @details="openDetails" @navigation="$emit('navigation')" />

    <div class="chat-view-scroll">
      <div class="chat-content">
        <ChatTranscript :entries="transcript" />
      </div>
    </div>

    <footer class="chat-view-footer">
      <div class="chat-content">
        <div v-if="!hasTranscript" class="chat-welcome">
          <h2>今天想聊些什么？</h2>
        </div>
        <ChatRequestStatus :state="chatState" :error="error" :workspace-notice="workspaceNotice"
          :pending-approvals="pendingApprovals" :approval-statuses="approvalStatuses"
          @retry="retry" @resume="resume" @approve="approve" @deny="deny" @details="openDetails" />
        <ChatRequestForm
          :catalog="providerCatalog"
          :skills="skills"
          :context-id="session?.context_id"
          :session-id="session?.session_id"
          :tools="toolCatalog"
          :busy="busy"
          :state="chatState"
          :can-stop="cancelableRun"
          :session-ready="true"
          :default-provider-id="session?.provider_id"
          :default-model-id="session?.model_id"
          @submit="send"
          @cancel="cancel"
        />
        <p class="chat-composer-hint">Enter 发送 · Shift + Enter 换行</p>
      </div>
    </footer>
    <ChatRunDetails :open="detailsOpen" :workspace-state="workspaceState" :chat-state="chatState"
      :workspace-issues="workspaceIssues" :provider-count="providerCatalog.providers.length"
      :tool-count="toolCatalog.length" :error="error" :has-transcript="hasTranscript" :busy="busy"
      :run="run" :trace="trace" :run-id="runId" :pending-approvals="pendingApprovals"
      @clear="clear" @close="closeDetails" />
  </section>
</template>
