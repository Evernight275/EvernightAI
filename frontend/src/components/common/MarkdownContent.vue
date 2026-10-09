<script setup lang="ts">
import { useMarkdownContent, type MarkdownContentProps } from './markdownContent';

const props = defineProps<MarkdownContentProps>();
const { blocks, copyCode } = useMarkdownContent(props);
</script>

<template>
  <div ref="content" class="markdown-content" @click="copyCode">
    <div v-for="(block, index) in blocks" :key="index" class="markdown-block" v-html="block"></div>
  </div>
</template>
