<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { Download, File } from '@lucide/vue';
import { getFileArtifact, readFileArtifact, type FileArtifactInfo } from '../../api/files';
import { authGeneration } from '../../runtime/workspaceRuntime';
import { htmlPreviewBlob } from './filePreview';

const props = defineProps<{ artifactId: string }>();
const file = shallowRef<FileArtifactInfo | null>(null);
const previewUrl = ref('');
const isHtml = computed(() => file.value?.mime_type === 'text/html');
const error = ref('');
const loading = ref(false);
const downloading = ref(false);
let controller = new AbortController();
let version = 0;
const size = computed(() => {
  const bytes = file.value?.size_bytes ?? 0;
  return bytes < 1024
    ? `${bytes} B`
    : bytes < 1024 * 1024
      ? `${(bytes / 1024).toFixed(1)} KiB`
      : `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
});
function clearPreview() {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value);
  previewUrl.value = '';
}
async function load() {
  const current = ++version;
  controller.abort();
  controller = new AbortController();
  clearPreview();
  file.value = null;
  error.value = '';
  downloading.value = false;
  loading.value = true;
  try {
    const saved = await getFileArtifact(props.artifactId, controller.signal);
    if (current !== version) return;
    file.value = saved;
    if (saved.preview_kind === 'image' || saved.mime_type === 'text/html') {
      const content = await readFileArtifact(props.artifactId, controller.signal);
      const preview = saved.mime_type === 'text/html' ? await htmlPreviewBlob(content) : content;
      if (current !== version || controller.signal.aborted) return;
      previewUrl.value = URL.createObjectURL(preview);
    }
  } catch (cause) {
    if (current === version && !controller.signal.aborted)
      error.value = cause instanceof Error ? cause.message : '无法读取展示文件';
  } finally {
    if (current === version) loading.value = false;
  }
}
async function download() {
  if (!file.value || downloading.value) return;
  const current = version;
  const name = file.value.name;
  downloading.value = true;
  error.value = '';
  try {
    const content = await readFileArtifact(props.artifactId, controller.signal, true);
    if (current !== version || controller.signal.aborted) return;
    const url = URL.createObjectURL(content);
    try {
      const link = document.createElement('a');
      link.href = url;
      link.download = name;
      link.click();
    } finally {
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
  } catch (cause) {
    if (current === version && !controller.signal.aborted)
      error.value = cause instanceof Error ? cause.message : '下载失败';
  } finally {
    if (current === version) downloading.value = false;
  }
}
watch([() => props.artifactId, authGeneration], () => void load(), {
  immediate: true,
  flush: 'sync',
});
onBeforeUnmount(() => {
  version++;
  controller.abort();
  clearPreview();
});
</script>
<template>
  <section class="chat-file-result" aria-label="工具展示文件" :aria-busy="loading">
    <p v-if="loading" class="chat-tool-image-notice" role="status">正在读取文件…</p>
    <figure v-if="file">
      <img
        v-if="previewUrl && !isHtml"
        :src="previewUrl"
        :alt="file.title || file.name"
        @error="error = '图片预览不可用，仍可下载文件。'"
      />
      <iframe
        v-if="previewUrl && isHtml"
        :src="previewUrl"
        :title="`HTML 预览：${file.title || file.name}`"
        sandbox="allow-scripts"
        allow="camera 'none'; microphone 'none'; geolocation 'none'"
        referrerpolicy="no-referrer"
      />
      <figcaption>
        <div>
          <strong
            ><File v-if="file.preview_kind !== 'image'" :size="16" aria-hidden="true" />{{
              file.title || file.name
            }}</strong
          >
          <small>{{ file.name }} · {{ size }}</small>
        </div>
        <button type="button" :disabled="downloading" @click="download">
          <Download :size="16" aria-hidden="true" />{{ downloading ? '正在下载…' : '下载文件' }}
        </button>
      </figcaption>
    </figure>
    <p v-if="error" class="chat-status-error" role="status">
      {{ error }} <button type="button" :disabled="loading" @click="load">重新读取文件</button>
    </p>
  </section>
</template>
