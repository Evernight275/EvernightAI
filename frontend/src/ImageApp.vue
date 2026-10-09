<script setup lang="ts">
import { nextTick, onBeforeUnmount, shallowRef, ref, watch } from 'vue';
import { Menu, RefreshCw } from '@lucide/vue';
import { workspaceActor } from './state/workspaceMachine';
import { authGeneration } from './runtime/workspaceRuntime';
import ImageGenerationView from './components/images/ImageGenerationView.vue';
import SettingsDialog from './components/settings/SettingsDialog.vue';
import ImageHistoryView from './components/images/ImageHistoryView.vue';
import ImageTaskList from './components/images/ImageTaskList.vue';
import ImageSidebar from './components/images/ImageSidebar.vue';
import { useChatLayout } from './components/chat/chatLayout';
import type { ImageGenerationRecord, ImageGenerationResponse } from './api/images';
const snapshot = shallowRef(workspaceActor.getSnapshot());
const subscription = workspaceActor.subscribe((value) => {
  snapshot.value = value;
});
const settingsOpen = ref(false);
const { navigationOpen, sidebarCollapsed, openNavigation, closeNavigation, collapseSidebar } =
  useChatLayout();
function openSettings(): void {
  closeNavigation();
  settingsOpen.value = true;
}
const imageBusy = ref(false);
const historyRefresh = ref(0);
const taskRefresh = ref(0);
const selectedRecord = ref<ImageGenerationRecord | null>(null);
const clearedRecordId = ref('');
const pageRoot = ref<HTMLElement | null>(null);
function generated(response: ImageGenerationResponse): void {
  if (response.record_id) historyRefresh.value++;
}
async function selectRecord(record: ImageGenerationRecord): Promise<void> {
  if (imageBusy.value) return;
  const identity = authGeneration.value;
  selectedRecord.value = record;
  await nextTick();
  if (identity !== authGeneration.value || selectedRecord.value?.record_id !== record.record_id)
    return;
  const preview = pageRoot.value?.querySelector<HTMLElement>('.image-results');
  preview?.focus({ preventScroll: true });
  preview?.scrollIntoView({ block: 'start', behavior: 'auto' });
}
function deletedRecord(id: string): void {
  clearedRecordId.value = id;
  if (selectedRecord.value?.record_id === id) selectedRecord.value = null;
}
watch(
  authGeneration,
  () => {
    selectedRecord.value = null;
    clearedRecordId.value = '';
    imageBusy.value = false;
  },
  { flush: 'sync' },
);
onBeforeUnmount(() => subscription.unsubscribe());
</script>
<template>
  <div class="chat-layout" :class="{ 'chat-layout--collapsed': sidebarCollapsed }">
    <ImageSidebar
      :open="navigationOpen"
      :collapsed="sidebarCollapsed"
      @close="closeNavigation"
      @collapse="collapseSidebar"
      @settings="openSettings"
    />
    <main ref="pageRoot" class="chat-main image-page">
      <header class="chat-view-header">
        <div class="chat-header-main">
          <button
            class="icon-button chat-navigation-toggle"
            type="button"
            aria-label="页面导航"
            title="页面导航"
            @click="openNavigation"
          >
            <Menu :size="18" aria-hidden="true" />
          </button>
          <div class="chat-header-heading">
            <h1 class="chat-header-title">图像生成</h1>
          </div>
          <button
            class="icon-button"
            type="button"
            title="刷新服务商"
            aria-label="刷新服务商"
            @click="workspaceActor.send({ type: 'REFRESH' })"
          >
            <RefreshCw :size="18" aria-hidden="true" />
          </button>
        </div>
      </header>
      <div class="image-page-content">
        <p v-if="snapshot.matches('offline')" class="image-error" role="alert">无法连接服务</p>
        <p
          v-for="issue in snapshot.context.issues.filter((i) => i.concept === 'providerCatalog')"
          :key="issue.resource"
          class="image-error"
          role="alert"
        >
          {{ issue.message }}
        </p>
        <ImageGenerationView
          :key="authGeneration"
          :providers="snapshot.context.workspace.providerCatalog.providers"
          :record="selectedRecord"
          :cleared-record-id="clearedRecordId"
          @generated="generated"
          @busy="imageBusy = $event"
          @queued="taskRefresh++"
        />
        <ImageTaskList
          :key="authGeneration"
          :refresh="taskRefresh"
          :disabled="imageBusy"
          @select="selectRecord"
        />
        <ImageHistoryView
          :key="authGeneration"
          :refresh="historyRefresh"
          :disabled="imageBusy"
          @select="selectRecord"
          @deleted="deletedRecord"
        />
      </div>
    </main>
    <SettingsDialog :open="settingsOpen" @close="settingsOpen = false" />
  </div>
</template>
