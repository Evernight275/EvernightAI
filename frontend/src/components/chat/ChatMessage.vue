<script setup lang="ts">
import { Bot, User } from '@lucide/vue'
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
    <span class="chat-message-icon" aria-hidden="true">
      <User v-if="presentation.roleClass === 'user'" :size="19" />
      <Bot v-else :size="19" />
    </span>
    <div class="chat-message-content">
      <header class="chat-message-header">
        <strong class="chat-message-role">{{ presentation.roleLabel }}</strong>
      </header>
      <MarkdownContent v-if="presentation.markdown" :source="entry.text" />
      <p v-else class="chat-message-text">{{ entry.text }}</p>
    </div>
  </article>
</template>
