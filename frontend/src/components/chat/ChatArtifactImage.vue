<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue';
import { readFileArtifact } from '../../api/files';
import { authGeneration } from '../../runtime/workspaceRuntime';
import { useDialog } from '../common/dialog';

const props = defineProps<{ artifactId: string; alt?: string }>();
const source = ref('');
const error = ref('');
const open = ref(false);
const { setDialog, onCancel, onBackdropClick, onKeydown } = useDialog(
  () => open.value,
  () => (open.value = false),
);
let controller: AbortController | null = null;
let currentUrl = '';

watch(
  [() => props.artifactId, authGeneration],
  async ([artifactId]) => {
    open.value = false;
    controller?.abort();
    if (currentUrl) URL.revokeObjectURL(currentUrl);
    currentUrl = '';
    source.value = '';
    error.value = '';
    const request = new AbortController();
    controller = request;
    try {
      const blob = await readFileArtifact(artifactId, request.signal);
      if (request.signal.aborted) return;
      currentUrl = URL.createObjectURL(blob);
      source.value = currentUrl;
    } catch (cause) {
      if (!request.signal.aborted)
        error.value = cause instanceof Error ? cause.message : '图片加载失败';
    }
  },
  { immediate: true },
);

onUnmounted(() => {
  controller?.abort();
  if (currentUrl) URL.revokeObjectURL(currentUrl);
});
</script>

<template>
  <button
    v-if="source"
    type="button"
    class="chat-message-image-button"
    :aria-label="`预览${alt || '对话图片'}`"
    @click="open = true"
  >
    <img class="chat-message-image" :src="source" :alt="alt || '对话图片'" />
  </button>
  <span v-else-if="error" class="chat-message-image-error" role="status"
    >图片无法载入：{{ error }}</span
  >
  <span v-else class="chat-message-image-loading" role="status">正在载入图片…</span>
  <dialog
    :ref="setDialog"
    class="chat-image-preview-dialog"
    :aria-label="`图片预览：${alt || '对话图片'}`"
    @cancel="onCancel"
    @click="onBackdropClick"
    @keydown="onKeydown"
  >
    <button type="button" aria-label="关闭图片预览" @click="open = false">关闭</button>
    <img v-if="source" :src="source" :alt="alt || '对话图片'" />
  </dialog>
</template>
