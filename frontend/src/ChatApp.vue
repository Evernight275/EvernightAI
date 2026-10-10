<script setup lang="ts">
import { defineAsyncComponent, onBeforeUnmount, onMounted, ref } from 'vue';
import { authGeneration } from './runtime/workspaceRuntime';
import SettingsDialog from './components/settings/SettingsDialog.vue';
import ChatSidebar from './components/chat/ChatSidebar.vue';
import ChatView from './components/chat/ChatView.vue';
import { useChatLayout } from './components/chat/chatLayout';

const ImageWorkspace = defineAsyncComponent(() => import('./components/images/ImageWorkspace.vue'));

// The image workspace is a view of this page, addressed as chat.html#images. It loads on
// first use and then stays mounted, like the chat, so drafts and running work survive a switch.
const imagesOpen = ref(false);
const imagesLoaded = ref(false);
function syncView(): void {
  imagesOpen.value = window.location.hash === '#images';
  if (imagesOpen.value) imagesLoaded.value = true;
}
function showChat(): void {
  if (window.location.hash !== '#images') return;
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
      :images-open="imagesOpen"
      @chat="showChat"
      @close="closeNavigation"
      @collapse="collapseSidebar"
      @settings="openSettings"
    />
    <main class="chat-main">
      <ChatView v-show="!imagesOpen" :key="authGeneration" @navigation="openNavigation" />
      <ImageWorkspace v-if="imagesLoaded" v-show="imagesOpen" @navigation="openNavigation" />
    </main>
    <SettingsDialog :open="settingsOpen" @close="settingsOpen = false" />
  </div>
</template>
