<script setup lang="ts">
import ChatSidebar from './components/chat/ChatSidebar.vue'
import ChatView from './components/chat/ChatView.vue'
</script>

<template>
  <div class="chat-layout">
    <ChatSidebar />
    <main class="chat-main">
      <ChatView />
    </main>
  </div>
</template>
