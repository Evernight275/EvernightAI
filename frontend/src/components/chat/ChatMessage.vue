<script setup lang="ts">
import { computed } from 'vue'
import type { ChatTranscriptEntry } from '../../domain/chat'
import MarkdownContent from '../common/MarkdownContent.vue'
import { chatMessagePresentation } from './chatMessage'

const props = defineProps<{
  entry: ChatTranscriptEntry
}>()

const presentation = computed(() => chatMessagePresentation(props.entry))
</script>

<template>
  <article :class="['chat-message', `chat-message--${presentation.roleClass}`]">
    <div class="chat-message-content">
      <header class="chat-message-header sr-only">
        <strong class="chat-message-role">{{ presentation.roleLabel }}</strong>
      </header>
      <MarkdownContent v-if="presentation.markdown" :source="entry.text" />
      <p v-else class="chat-message-text">{{ entry.text }}</p>
      <span v-if="entry.streaming" class="chat-stream-cursor" role="status" aria-label="正在生成回复"></span>
    </div>
  </article>
</template>
