<script setup lang="ts">
import type { ChatTranscriptEntry } from '../../domain/chat'
import EmptyValue from '../common/EmptyValue.vue'
import ChatMessage from './ChatMessage.vue'
import { useChatTranscript } from './chatTranscript'

const props = defineProps<{
  entries: ChatTranscriptEntry[]
}>()

const { setEndMarker } = useChatTranscript(() => props.entries)
</script>

<template>
  <section class="chat-transcript" aria-label="对话记录">
    <div v-if="!entries.length" class="chat-transcript-empty">
      <EmptyValue label="还没有消息" />
    </div>
    <ol v-else class="chat-transcript-list">
      <li v-for="entry in entries" :key="entry.entryId">
        <ChatMessage :entry="entry" />
      </li>
    </ol>
    <span :ref="setEndMarker" aria-hidden="true"></span>
  </section>
</template>
