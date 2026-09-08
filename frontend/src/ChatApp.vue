<script setup lang="ts">
import ChatSidebar from './components/chat/ChatSidebar.vue'
import ChatView from './components/chat/ChatView.vue'
import { useChatLayout } from './components/chat/chatLayout'

const { navigationOpen, sidebarCollapsed, openNavigation, closeNavigation, collapseSidebar } = useChatLayout()
</script>

<template>
  <div class="chat-layout" :class="{ 'chat-layout--collapsed': sidebarCollapsed }">
    <ChatSidebar :open="navigationOpen" :collapsed="sidebarCollapsed" @close="closeNavigation" @collapse="collapseSidebar" />
    <main class="chat-main">
      <ChatView @navigation="openNavigation" />
    </main>
  </div>
</template>
