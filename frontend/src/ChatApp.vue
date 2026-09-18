<script setup lang="ts">
import { ref } from 'vue'
import SettingsDialog from './components/settings/SettingsDialog.vue'
import ChatSidebar from './components/chat/ChatSidebar.vue'
import ChatView from './components/chat/ChatView.vue'
import { useChatLayout } from './components/chat/chatLayout'

const settingsOpen = ref(false)
function openSettings(): void {
  closeNavigation()
  settingsOpen.value = true
}

const { navigationOpen, sidebarCollapsed, openNavigation, closeNavigation, collapseSidebar } = useChatLayout()
</script>

<template>
  <div class="chat-layout" :class="{ 'chat-layout--collapsed': sidebarCollapsed }">
    <ChatSidebar :open="navigationOpen" :collapsed="sidebarCollapsed" @close="closeNavigation" @collapse="collapseSidebar" @settings="openSettings" />
    <main class="chat-main">
      <ChatView @navigation="openNavigation" />
    </main>
    <SettingsDialog :open="settingsOpen" @close="settingsOpen = false" />
  </div>
</template>
