<script setup lang="ts">
import { onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { getImageRecord, type GeneratedImage, type ImageGenerationRecord } from '../../api/images';
import { defaultImageDownloadName, downloadImage, imageSource } from '../../domain/images';
import { authGeneration } from '../../runtime/workspaceRuntime';

const props = defineProps<{ recordId: string }>();
const record = shallowRef<ImageGenerationRecord | null>(null);
const error = ref('');
const loading = ref(false);
const names = ref<string[]>([]);
const downloading = ref<number | null>(null);
let controller = new AbortController();
let version = 0;
async function load(): Promise<void> {
  const current = ++version;
  controller.abort();
  controller = new AbortController();
  record.value = null;
  names.value = [];
  downloading.value = null;
  error.value = '';
  loading.value = true;
  try {
    const saved = await getImageRecord(props.recordId, controller.signal);
    if (current !== version) return;
    record.value = saved;
    const date = new Date();
    names.value = saved.response.images.map((_, index) => defaultImageDownloadName(index, date));
  } catch (cause) {
    if (current === version && !controller.signal.aborted)
      error.value = cause instanceof Error ? cause.message : '无法读取生成图片';
  } finally {
    if (current === version) loading.value = false;
  }
}
watch([() => props.recordId, authGeneration], () => void load(), {
  immediate: true,
  flush: 'sync',
});
async function download(image: GeneratedImage, index: number): Promise<void> {
  if (downloading.value !== null) return;
  const current = version;
  downloading.value = index;
  error.value = '';
  try {
    await downloadImage(image, index, controller.signal, names.value[index]);
  } catch (cause) {
    if (current === version) error.value = cause instanceof Error ? cause.message : '下载失败';
  } finally {
    if (current === version) downloading.value = null;
  }
}
onBeforeUnmount(() => {
  version++;
  controller.abort();
});
</script>
<template>
  <section class="chat-image-result" aria-label="工具生成图片" :aria-busy="loading">
    <p v-if="loading" class="chat-tool-image-notice" role="status">正在读取生成图片…</p>
    <div v-if="record" class="chat-tool-images">
      <figure v-for="(image, index) in record.response.images" :key="index">
        <img
          :src="imageSource(image)"
          :alt="`工具生成图片 ${index + 1}`"
          referrerpolicy="no-referrer"
        />
        <figcaption>
          <span>图片 {{ index + 1 }}</span>
          <button type="button" :disabled="downloading !== null" @click="download(image, index)">
            下载图片 {{ index + 1 }}
          </button>
        </figcaption>
        <label
          >文件名<input
            v-model="names[index]"
            :aria-label="`工具图片 ${index + 1} 文件名`"
            maxlength="80"
            :disabled="downloading !== null"
        /></label>
      </figure>
    </div>
    <p v-if="record?.response.persistence_warning" class="chat-tool-image-notice" role="status">
      部分图片未能归档，请先下载保存。
    </p>
    <p v-if="record" class="chat-tool-image-notice">可以直接发送修改要求，继续修改这些图片。</p>
    <p v-if="error" class="chat-status-error" role="status">
      {{ error }} <button v-if="!record" type="button" @click="load">重新读取图片</button>
    </p>
  </section>
</template>
