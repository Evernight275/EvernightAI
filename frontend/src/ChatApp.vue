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
  height: 100%;
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
  height: 100vh;
  overflow: hidden;
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
  min-height: 0;
  overflow: hidden;
}

.chat-view {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  height: 100%;
  min-height: 0;
}

.chat-content {
  width: min(100%, 900px);
  margin: 0 auto;
}

.chat-view-header {
  border-bottom: 1px solid #ccc;
  padding: 16px 24px;
}

.chat-view-header h1 {
  margin: 0 0 8px;
  font-size: 20px;
}

.chat-view-header > .chat-content > p {
  margin: 0 0 12px;
}

.chat-details {
  margin-top: 16px;
}

.chat-details summary {
  cursor: pointer;
}

.chat-details-content {
  display: grid;
  gap: 16px;
  margin-top: 12px;
}

.chat-details-content h2 {
  margin: 0 0 4px;
  font-size: 16px;
}

.chat-details-content .chat-prerequisites p {
  display: inline;
  margin: 0 16px 0 0;
}

.chat-view-scroll {
  min-height: 0;
  overflow-y: auto;
  padding: 24px;
}

.chat-flow section > h2:first-child {
  margin-top: 0;
}

.chat-transcript ol {
  margin: 0;
  padding-left: 24px;
}

.chat-transcript li {
  padding: 8px 0;
  border-bottom: 1px solid #ddd;
}

.chat-transcript pre,
.chat-request-status pre {
  max-width: 100%;
  overflow-x: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.chat-view-footer {
  border-top: 1px solid #ccc;
  padding: 16px 24px;
  background: #fff;
}

.chat-composer h2 {
  margin: 0 0 8px;
  font-size: 16px;
}

.chat-composer form {
  display: grid;
  gap: 8px;
}

.chat-composer-options {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
}

.chat-composer-options label {
  display: grid;
  grid-template-columns: auto minmax(120px, 240px);
  align-items: center;
  gap: 8px;
}

.chat-composer-options select {
  min-width: 0;
  width: 100%;
}

.chat-composer-message {
  display: grid;
  gap: 4px;
}

.chat-composer textarea {
  display: block;
  width: 100%;
  min-height: 64px;
  height: 88px;
  max-height: 160px;
  resize: vertical;
}

.chat-composer button[type='submit'] {
  justify-self: start;
}

@media (max-width: 720px) {
  html,
  body,
  #app {
    height: auto;
    min-height: 100%;
  }

  .chat-layout {
    display: block;
    height: auto;
    min-height: 100vh;
    overflow: visible;
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
    overflow: visible;
  }

  .chat-view {
    display: flex;
    flex-direction: column;
    min-height: 720px;
  }

  .chat-view-header,
  .chat-view-scroll,
  .chat-view-footer {
    padding-right: 16px;
    padding-left: 16px;
  }

  .chat-view-scroll {
    flex: 1;
    overflow: visible;
  }

  .chat-composer-options {
    display: grid;
  }

  .chat-composer-options label {
    grid-template-columns: 80px minmax(0, 1fr);
  }
}
</style>
