<script setup lang="ts">
import { computed } from 'vue';
import { renderJson } from './jsonContent';

const props = defineProps<{ source: string }>();
const html = computed(() => renderJson(props.source));
</script>

<template>
  <code class="json-code" v-html="html"></code>
</template>

<style scoped>
.json-code {
  display: block;
  color: #334155;
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 400;
  line-height: 1.7;
  letter-spacing: 0;
  font-variant-ligatures: none;
  tab-size: 2;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}
.json-code :deep(.hljs-attr) {
  color: #1d4ed8;
}
.json-code :deep(.hljs-string) {
  color: #087f5b;
}
.json-code :deep(.hljs-number) {
  color: #a64b08;
}
.json-code :deep(.hljs-literal) {
  color: #7c3aed;
}
.json-code :deep(.hljs-punctuation) {
  color: #64748b;
}
</style>
