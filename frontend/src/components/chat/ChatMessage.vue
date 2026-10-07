<script setup lang="ts">
import { computed } from 'vue';
import type { ChatTranscriptEntry } from '../../domain/chat';
import MarkdownContent from '../common/MarkdownContent.vue';
import { chatMessagePresentation } from './chatMessage';
import ChatArtifactImage from './ChatArtifactImage.vue';

const props = defineProps<{
  entry: ChatTranscriptEntry;
}>();

const presentation = computed(() => chatMessagePresentation(props.entry));
const images = computed(() =>
  (props.entry.content.content || []).filter((part) => part.type === 'image'),
);
</script>

<template>
  <article :class="['chat-message', `chat-message--${presentation.roleClass}`]">
    <div class="chat-message-content">
      <header class="chat-message-header sr-only">
        <strong class="chat-message-role">{{ presentation.roleLabel }}</strong>
      </header>
      <MarkdownContent v-if="presentation.markdown" :source="entry.text" />
      <p v-else class="chat-message-text">{{ entry.text }}</p>
      <div v-if="images.length" class="chat-message-images">
        <template v-for="(image, index) in images" :key="image.artifact_id || image.url || index">
          <ChatArtifactImage
            v-if="image.artifact_id"
            :artifact-id="image.artifact_id"
            :alt="String(image.metadata?.filename || `图片 ${index + 1}`)"
          />
          <img
            v-else-if="image.url"
            class="chat-message-image"
            :src="image.url"
            :alt="`图片 ${index + 1}`"
          />
        </template>
      </div>
      <span
        v-if="entry.streaming"
        class="chat-stream-cursor"
        role="status"
        aria-label="正在生成回复"
      ></span>
    </div>
  </article>
</template>
