<script setup lang="ts">
import { nextTick, onBeforeUnmount, shallowRef, ref, watch } from 'vue'
import { ArrowLeft, Settings, RefreshCw } from '@lucide/vue'
import { workspaceActor } from './state/workspaceMachine'
import { authGeneration } from './runtime/workspaceRuntime'
import ImageGenerationView from './components/images/ImageGenerationView.vue'
import SettingsDialog from './components/settings/SettingsDialog.vue'
import ImageHistoryView from './components/images/ImageHistoryView.vue'
import type { ImageGenerationRecord, ImageGenerationResponse } from './api/images'
const snapshot = shallowRef(workspaceActor.getSnapshot())
const subscription = workspaceActor.subscribe(value => { snapshot.value = value })
const settingsOpen = ref(false)
const imageBusy = ref(false)
const historyRefresh = ref(0)
const selectedRecord = ref<ImageGenerationRecord | null>(null)
const clearedRecordId = ref('')
const pageRoot = ref<HTMLElement | null>(null)
function generated(response: ImageGenerationResponse): void { if (response.record_id) historyRefresh.value++ }
async function selectRecord(record: ImageGenerationRecord): Promise<void> {
  if (imageBusy.value) return
  const identity = authGeneration.value
  selectedRecord.value = record
  await nextTick()
  if (identity !== authGeneration.value || selectedRecord.value?.record_id !== record.record_id) return
  const preview = pageRoot.value?.querySelector<HTMLElement>('.image-results')
  preview?.focus({ preventScroll: true })
  preview?.scrollIntoView({ block: 'start', behavior: 'auto' })
}
function deletedRecord(id: string): void { clearedRecordId.value = id; if (selectedRecord.value?.record_id === id) selectedRecord.value = null }
watch(authGeneration, () => { selectedRecord.value = null; clearedRecordId.value = ''; imageBusy.value = false }, { flush: 'sync' })
onBeforeUnmount(() => subscription.unsubscribe())
</script>
<template>
  <main ref="pageRoot" class="image-page">
    <header class="image-page-header">
      <div class="image-page-header-content">
        <a class="icon-button" href="/chat.html" title="返回会话" aria-label="返回会话"><ArrowLeft :size="18" /></a>
        <div class="image-page-heading"><span class="image-brand-mark" aria-hidden="true">E</span><h1>图像生成<span>EvernightAI</span></h1></div>
        <div class="image-actions">
          <button class="icon-button" title="刷新服务商" aria-label="刷新服务商" @click="workspaceActor.send({ type: 'REFRESH' })"><RefreshCw :size="18" /></button>
          <button class="icon-button" title="设置" aria-label="设置" aria-haspopup="dialog" :aria-expanded="settingsOpen" @click="settingsOpen = true"><Settings :size="18" /></button>
        </div>
      </div>
    </header>
    <div class="image-page-content">
      <p v-if="snapshot.matches('offline')" class="image-error" role="alert">无法连接服务</p>
      <p v-for="issue in snapshot.context.issues.filter(i => i.concept === 'providerCatalog')" :key="issue.resource" class="image-error" role="alert">{{ issue.message }}</p>
      <ImageGenerationView :key="authGeneration" :providers="snapshot.context.workspace.providerCatalog.providers" :record="selectedRecord" :cleared-record-id="clearedRecordId" @generated="generated" @busy="imageBusy = $event" />
      <ImageHistoryView :key="authGeneration" :refresh="historyRefresh" :disabled="imageBusy" @select="selectRecord" @deleted="deletedRecord" />
    </div>
    <SettingsDialog :open="settingsOpen" @close="settingsOpen = false" />
  </main>
</template>
