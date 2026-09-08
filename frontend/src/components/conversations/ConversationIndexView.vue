<script setup lang="ts">
import type { ConversationIndex } from '../../domain/workspace'
import EmptyValue from '../common/EmptyValue.vue'

defineProps<{
  index: ConversationIndex
}>()
</script>

<template>
  <section class="settings-resource-section">
    <h2>会话索引（{{ index.sessions.length }}）</h2>
    <EmptyValue v-if="!index.sessions.length" label="没有会话" />
    <ul v-else>
      <li v-for="session in index.sessions" :key="session.session_id">
        <strong>{{ session.title || session.session_id }}</strong>
        <span> / {{ session.status || 'active' }}</span>
        <span> / context: {{ session.context_id }}</span>
        <span v-if="session.provider_id"> / provider: {{ session.provider_id }}</span>
        <span v-if="session.model_id"> / model: {{ session.model_id }}</span>
      </li>
    </ul>
  </section>
</template>
