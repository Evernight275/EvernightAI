<script setup lang="ts">
import {
  useMarkdownContent,
  type MarkdownContentProps,
} from './markdownContent'

const props = defineProps<MarkdownContentProps>()
const { html, copyCode } = useMarkdownContent(props)
</script>

<template>
  <div class="markdown-content" @click="copyCode" v-html="html"></div>
</template>
