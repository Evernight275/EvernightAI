<script setup lang="ts">
import ChatHeader from './ChatHeader.vue';
import ChatRequestForm from './ChatRequestForm.vue';
import ChatRequestStatus from './ChatRequestStatus.vue';
import ChatRunDetails from './ChatRunDetails.vue';
import ChatTranscript from './ChatTranscript.vue';
import RunSkillConflict from '../skills/RunSkillConflict.vue';
import { useChatView } from './chatView';

defineEmits<{ navigation: [] }>();

const {
  skills,
  workspaceState,
  chatState,
  connection,
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
  retryTools,
  session,
  trace,
  runId,
  pendingApprovals,
  approvalStatuses,
  cancelableRun,
  send,
  retry,
  replyOnly,
  clear,
  cancel,
  approve,
  deny,
  resume,
  skillIssues,
  editing,
  editRun,
  editRequest,
  contextId,
  authGeneration,
} = useChatView();
</script>

<template>
  <section class="chat-view" :class="{ 'chat-view--empty': !hasTranscript }">
    <ChatHeader
      :session="session"
      :state="chatState"
      :details-open="detailsOpen"
      @details="openDetails"
      @navigation="$emit('navigation')"
    />

    <div class="chat-view-scroll">
      <div class="chat-content">
        <ChatTranscript
          :entries="transcript"
          :tools="toolCatalog"
          :run-id="runId"
          :pending-approvals="pendingApprovals"
          :approval-statuses="approvalStatuses"
          :can-approve="chatState === 'approvalRequired' && !skillIssues.length"
          @approve="approve"
          @deny="deny"
        />
      </div>
    </div>

    <footer class="chat-view-footer">
      <div class="chat-content">
        <div v-if="!hasTranscript" class="chat-welcome">
          <h2>今天想聊些什么？</h2>
        </div>
        <p
          v-if="
            ['streaming', 'resuming', 'retrying', 'recovering'].includes(chatState) &&
            connection !== 'live'
          "
          class="chat-connection-notice"
          role="status"
        >
          {{
            connection === 'reconnecting'
              ? '连接中断，正在自动重连…'
              : '连接已恢复，正在同步运行进度…'
          }}
        </p>
        <RunSkillConflict :issues="skillIssues" :run="run" :busy="editing" @edit="editRun" />
        <ChatRequestStatus
          :state="chatState"
          :error="error"
          :workspace-notice="workspaceNotice"
          :pending-approvals="pendingApprovals"
          :approval-statuses="approvalStatuses"
          :skill-conflict="skillIssues.length > 0"
          :retry-blocked="run?.status === 'finished'"
          :retry-tools="retryTools"
          :run-id="runId"
          :can-reply-only="!!run && ['failed', 'canceled'].includes(run.status || '')"
          @retry="retry"
          @reply-only="replyOnly"
          @resume="resume"
          @details="openDetails"
        />
        <ChatRequestForm
          :key="authGeneration"
          :catalog="providerCatalog"
          :skills="skills"
          :context-id="contextId"
          :session-id="session?.session_id"
          :tools="toolCatalog"
          :busy="busy"
          :state="chatState"
          :can-stop="cancelableRun"
          :session-ready="true"
          :default-provider-id="session?.provider_id"
          :default-model-id="session?.model_id"
          :edit-request="editRequest"
          @submit="send"
          @cancel="cancel"
        />
        <p class="chat-composer-hint">Enter 发送 · Shift + Enter 换行</p>
      </div>
    </footer>
    <ChatRunDetails
      :open="detailsOpen"
      :workspace-state="workspaceState"
      :chat-state="chatState"
      :workspace-issues="workspaceIssues"
      :provider-count="providerCatalog.providers.length"
      :tool-count="toolCatalog.length"
      :error="error"
      :has-transcript="hasTranscript"
      :busy="busy"
      :run="run"
      :trace="trace"
      :run-id="runId"
      :pending-approvals="pendingApprovals"
      @clear="clear"
      @close="closeDetails"
    />
  </section>
</template>
