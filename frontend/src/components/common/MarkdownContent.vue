<script setup lang="ts">
import {
  useMarkdownContent,
  type MarkdownContentProps,
} from './markdownContent'

const props = defineProps<MarkdownContentProps>()
const { html } = useMarkdownContent(props)
</script>

<template>
  <div class="markdown-content" v-html="html"></div>
</template>
