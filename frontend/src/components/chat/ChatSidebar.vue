<script setup lang="ts">
import EmptyValue from '../common/EmptyValue.vue'
import { useChatSidebar } from './chatSidebar'

const { sessions, newConversation, selectSession } = useChatSidebar()
</script>

<template>
  <aside class="chat-sidebar" aria-label="会话管理">
    <header class="chat-sidebar-header">
      <h1>会话</h1>
      <button type="button" @click="newConversation">新建会话</button>
    </header>

    <section class="chat-sidebar-sessions" aria-label="会话列表">
      <EmptyValue v-if="sessions.length === 0" label="没有会话" />
      <ul v-else class="chat-sidebar-list">
        <li v-for="session in sessions" :key="session.id">
          <button
            type="button"
            :disabled="session.active"
            :aria-current="session.active ? 'true' : undefined"
            @click="selectSession(session.id)"
          >
            {{ session.title }}
          </button>
          <small>{{ session.status }}</small>
        </li>
      </ul>
    </section>

    <footer class="chat-sidebar-settings">
      <a href="/">设置</a>
    </footer>
  </aside>
</template>
