<script setup lang="ts">
import type { ChatTranscriptEntry } from '../../domain/chat'
import EmptyValue from '../common/EmptyValue.vue'

defineProps<{
  entries: ChatTranscriptEntry[]
}>()
</script>

<template>
  <section>
    <h2>本地对话记录（{{ entries.length }}）</h2>
    <EmptyValue v-if="!entries.length" label="还没有消息" />
    <ol v-else>
      <li v-for="entry in entries" :key="entry.entryId">
        <p>
          <strong>{{ entry.role }}</strong>
          <span v-if="entry.modelId"> / {{ entry.modelId }}</span>
          <span v-if="entry.finishReason"> / {{ entry.finishReason }}</span>
        </p>
        <pre>{{ entry.text }}</pre>
      </li>
    </ol>
  </section>
</template>
