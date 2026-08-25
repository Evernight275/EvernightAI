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
    <header class="chat-view-header">
      <div class="chat-content">
        <h1>EvernightAI Chat</h1>
        <p v-if="session">当前会话：{{ session.title || session.session_id }}</p>
        <p v-else>请选择或新建会话</p>

        <details class="chat-details" :open="detailsOpen">
          <summary>运行详情</summary>
          <div class="chat-details-content">
            <ChatPrerequisites
              :state="workspaceState"
              :provider-count="providerCatalog.providers.length"
              :tool-count="toolCatalog.length"
              :issues="workspaceIssues"
            />

            <ChatToolActivity :run="run" :trace="trace" />

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
          </div>
        </details>
      </div>
    </header>

    <div class="chat-view-scroll">
      <div class="chat-content chat-flow">
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
