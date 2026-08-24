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

<style>
* {
  box-sizing: border-box;
}

html,
body,
#app {
  min-height: 100%;
  margin: 0;
}

body {
  background: #fff;
  color: #111;
  font-family: sans-serif;
}

.chat-layout {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  min-height: 100vh;
}

.chat-sidebar {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  max-height: 100vh;
  border-right: 1px solid #ccc;
  padding: 16px;
}

.chat-sidebar-header {
  border-bottom: 1px solid #ccc;
  padding-bottom: 16px;
}

.chat-sidebar-header h1 {
  margin: 0 0 12px;
  font-size: 20px;
}

.chat-sidebar-sessions {
  min-height: 0;
  overflow-y: auto;
  padding: 16px 0;
}

.chat-sidebar-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.chat-sidebar-list li {
  display: grid;
  gap: 4px;
  padding: 8px 0;
}

.chat-sidebar-list small {
  color: #555;
}

.chat-sidebar-settings {
  margin-top: auto;
  border-top: 1px solid #ccc;
  padding-top: 16px;
}

.chat-main {
  min-width: 0;
  padding: 24px;
}

@media (max-width: 720px) {
  .chat-layout {
    display: block;
  }

  .chat-sidebar {
    min-height: auto;
    max-height: none;
    border-right: 0;
    border-bottom: 1px solid #ccc;
  }

  .chat-sidebar-sessions {
    max-height: 240px;
  }

  .chat-sidebar-settings {
    margin-top: 0;
  }

  .chat-main {
    padding: 16px;
  }
}
</style>
