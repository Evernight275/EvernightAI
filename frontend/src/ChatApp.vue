<script setup lang="ts">
import ChatSidebar from './components/chat/ChatSidebar.vue'
import ChatView from './components/chat/ChatView.vue'
import { useChatLayout } from './components/chat/chatLayout'

const { navigationOpen, openNavigation, closeNavigation } = useChatLayout()
</script>

<template>
  <div class="chat-layout">
    <ChatSidebar :open="navigationOpen" @close="closeNavigation" />
    <main class="chat-main">
      <ChatView @navigation="openNavigation" />
    </main>
  </div>
</template>
