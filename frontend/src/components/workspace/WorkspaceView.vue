<script setup lang="ts">
import { computed, onUnmounted, ref, shallowRef } from 'vue'
import { X, KeyRound, Server, SlidersHorizontal } from '@lucide/vue'
import { workspaceActor } from '../../state/workspaceMachine'
import ApiKeySettings from '../settings/ApiKeySettings.vue'
import WorkspaceContents from './WorkspaceContents.vue'
import WorkspaceIssues from './WorkspaceIssues.vue'
import WorkspaceStatus from './WorkspaceStatus.vue'

defineProps<{ embedded?: boolean }>()
defineEmits<{ close: [] }>()
const snapshot = shallowRef(workspaceActor.getSnapshot())
const subscription = workspaceActor.subscribe((next) => { snapshot.value = next })
onUnmounted(() => subscription.unsubscribe())
const state = computed(() => String(snapshot.value.value))
const context = computed(() => snapshot.value.context)
const activeSection = ref('general')
const sections = [
  { id: 'general', label: '常规', icon: SlidersHorizontal },
  { id: 'connections', label: '连接与认证', icon: Server },
  { id: 'privacy', label: '数据控制', icon: KeyRound },
]
function refresh(): void { workspaceActor.send({ type: 'REFRESH' }) }
</script>

<template>
  <div class="settings-page-frame">
    <section class="settings-shell" aria-label="设置">
      <header class="settings-titlebar">
        <h1>设置</h1>
        <button v-if="embedded" type="button" class="settings-close" aria-label="关闭设置" @click="$emit('close')"><X :size="20" aria-hidden="true" /></button>
        <a v-else class="settings-close" href="/chat.html" aria-label="返回聊天"><X :size="20" aria-hidden="true" /></a>
      </header>
      <nav class="settings-nav" aria-label="设置分类">
        <button v-for="section in sections" :key="section.id" type="button"
          :aria-current="activeSection === section.id ? 'page' : undefined" @click="activeSection = section.id">
          <component :is="section.icon" :size="18" aria-hidden="true" /><span>{{ section.label }}</span>
        </button>
      </nav>
      <div class="settings-content" :key="activeSection">
        <h2 class="settings-section-title">{{ sections.find((section) => section.id === activeSection)?.label }}</h2>
        <template v-if="activeSection === 'general'">
          <WorkspaceStatus :state="state" :loaded-at="context.workspace.loadedAt" :connection-error="context.connectionError" @refresh="refresh" />
          <div class="settings-row"><div><h3>模型服务</h3><p>查看可用模型与访问凭证。</p></div>
            <button type="button" @click="activeSection = 'connections'">管理</button></div>
          <div class="settings-row"><div><h3>EvernightAI</h3><p>你的 AI 聊天工作区</p></div><span class="settings-value">网页版</span></div>
          <WorkspaceIssues :issues="context.issues" />
        </template>
        <template v-else-if="activeSection === 'connections'">
          <ApiKeySettings />
          <div class="settings-row"><div><h3>可用模型</h3><p>{{ context.workspace.providerCatalog.providers.length }} 个服务 · {{ context.workspace.providerCatalog.modelGroups.reduce((count, group) => count + group.models.length, 0) }} 个模型</p></div>
            <button type="button" :disabled="state === 'loading'" @click="refresh">刷新</button></div>
          <details class="settings-resource-details" v-if="context.workspace.loadedAt"><summary>查看工作区资源</summary><WorkspaceContents :workspace="context.workspace" /></details>
        </template>
        <template v-else>
          <div class="settings-row"><div><h3>聊天记录</h3><p>会话保存在 EvernightAI 服务端，可在聊天侧栏中逐个删除。</p></div></div>
          <div class="settings-row"><div><h3>浏览器凭证</h3><p>保存的 API Key 位于此浏览器的本地存储中。</p></div>
            <button type="button" @click="activeSection = 'connections'">管理凭证</button></div>
          <p class="settings-help">清除浏览器凭证不会删除服务端会话。删除会话不会清除浏览器凭证。</p>
        </template>
      </div>
    </section>
  </div>
</template>
