<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue';
import { getImageRecord, type ImageGenerationRecord } from '../../api/images';
import { imageTaskActive, imageTaskLabels, useImageTasks } from '../../runtime/imageTasks';
import { authGeneration } from '../../runtime/workspaceRuntime';

const props = defineProps<{ refresh?: number; disabled?: boolean }>();
const emit = defineEmits<{ select: [record: ImageGenerationRecord] }>();
const { tasks, error, loading, cursor, reload } = useImageTasks();
const resultErrors = ref<Record<string, string>>({});
const pending = new Set<string>();
let controller = new AbortController();
let version = 0;
watch(
  () => props.refresh,
  () => void reload(),
);
watch(
  authGeneration,
  () => {
    version++;
    controller.abort();
    controller = new AbortController();
    resultErrors.value = {};
    pending.clear();
  },
  { flush: 'sync' },
);
async function load(recordId: string): Promise<void> {
  if (pending.has(recordId)) return;
  const current = version;
  pending.add(recordId);
  try {
    const record = await getImageRecord(recordId, controller.signal);
    if (current !== version) return;
    delete resultErrors.value[recordId];
    emit('select', record);
  } catch (cause) {
    if (current === version)
      resultErrors.value[recordId] = cause instanceof Error ? cause.message : '无法读取图片';
  } finally {
    if (current === version) pending.delete(recordId);
  }
}
onBeforeUnmount(() => {
  version++;
  controller.abort();
});
</script>
<template>
  <section class="image-task-list" aria-label="图片任务">
    <header class="image-task-heading">
      <h2>图片任务</h2>
      <button type="button" :disabled="loading" @click="reload()">刷新任务</button>
    </header>
    <p class="image-muted">提交后在后台生成，刷新或离开页面后仍可查看状态和结果。</p>
    <p v-if="error" class="image-error" role="status">{{ error }}</p>
    <p v-if="!tasks.length && !loading" class="image-muted">暂无图片任务</p>
    <ol class="image-task-items">
      <li
        v-for="task in tasks"
        :key="task.task_id"
        class="image-task-card"
        :data-task-id="task.task_id"
      >
        <header>
          <span :class="{ 'image-task-active': imageTaskActive(task) }" role="status">{{
            imageTaskLabels[task.status]
          }}</span
          ><span class="image-muted"
            >{{ task.kind === 'edit' ? '改图' : '生图' }} · {{ task.model_id }}</span
          >
        </header>
        <p class="image-task-prompt">{{ task.prompt_preview }}</p>
        <p v-if="task.error_message" class="image-error" role="status">{{ task.error_message }}</p>
        <button
          v-if="task.record_id"
          type="button"
          :disabled="disabled"
          @click="load(task.record_id)"
        >
          查看结果
        </button>
        <p v-if="task.record_id && resultErrors[task.record_id]" class="image-error" role="status">
          {{ resultErrors[task.record_id] }}
        </p>
      </li>
    </ol>
    <button v-if="cursor" type="button" :disabled="loading" @click="reload(true)">
      加载更多任务
    </button>
  </section>
</template>
