<script setup lang="ts">
import { defineAsyncComponent, onBeforeUnmount, onMounted, ref } from 'vue';
import { authGeneration } from './runtime/workspaceRuntime';
import SettingsDialog from './components/settings/SettingsDialog.vue';
import ChatSidebar from './components/chat/ChatSidebar.vue';
import ChatView from './components/chat/ChatView.vue';
import { useChatLayout, type ChatPageView } from './components/chat/chatLayout';

const ImageWorkspace = defineAsyncComponent(() => import('./components/images/ImageWorkspace.vue'));
const DataWorkspace = defineAsyncComponent(() => import('./components/data/DataWorkspace.vue'));

// The image and data workspaces are views of this page, addressed as chat.html#images and
// chat.html#data. Each loads on first use and then stays mounted, like the chat, so drafts
// and running work survive a switch.
const view = ref<ChatPageView>('chat');
const opened = ref(new Set<ChatPageView>());
function syncView(): void {
  const hash = window.location.hash;
  view.value = hash === '#images' ? 'images' : hash === '#data' ? 'data' : 'chat';
  opened.value = new Set(opened.value).add(view.value);
}
function showChat(): void {
  if (view.value === 'chat') return;
  window.history.pushState(null, '', window.location.pathname + window.location.search);
  syncView();
}
onMounted(() => {
  syncView();
  window.addEventListener('hashchange', syncView);
});
onBeforeUnmount(() => window.removeEventListener('hashchange', syncView));

const settingsOpen = ref(false);
function openSettings(): void {
  closeNavigation();
  settingsOpen.value = true;
}

const { navigationOpen, sidebarCollapsed, openNavigation, closeNavigation, collapseSidebar } =
  useChatLayout();
</script>

<template>
  <div class="chat-layout" :class="{ 'chat-layout--collapsed': sidebarCollapsed }">
    <ChatSidebar
      :open="navigationOpen"
      :collapsed="sidebarCollapsed"
      :view="view"
      @chat="showChat"
      @close="closeNavigation"
      @collapse="collapseSidebar"
      @settings="openSettings"
    />
    <main class="chat-main">
      <ChatView v-show="view === 'chat'" :key="authGeneration" @navigation="openNavigation" />
      <ImageWorkspace
        v-if="opened.has('images')"
        v-show="view === 'images'"
        @navigation="openNavigation"
      />
      <DataWorkspace
        v-if="opened.has('data')"
        v-show="view === 'data'"
        :key="authGeneration"
        :active="view === 'data'"
        @navigation="openNavigation"
      />
    </main>
    <SettingsDialog :open="settingsOpen" @close="settingsOpen = false" />
  </div>
</template>
