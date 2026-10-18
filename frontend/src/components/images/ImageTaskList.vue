<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { deleteImageTask, getImageRecord, type ImageGenerationRecord } from '../../api/images';
import {
  imageTaskActive,
  imageTaskLabels,
  imageTaskRemovable,
  useImageTasks,
} from '../../runtime/imageTasks';
import { authGeneration } from '../../runtime/workspaceRuntime';

const props = defineProps<{ refresh?: number; disabled?: boolean }>();
const emit = defineEmits<{ select: [record: ImageGenerationRecord] }>();
const { tasks, error, loading, cursor, reload } = useImageTasks();
const resultErrors = ref<Record<string, string>>({});
const removing = ref(false);
const removeError = ref('');
const removable = computed(() => tasks.value.filter(imageTaskRemovable));
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
    removeError.value = '';
    removing.value = false;
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
async function remove(taskIds: string[]): Promise<void> {
  if (removing.value || !taskIds.length) return;
  const current = version;
  removing.value = true;
  removeError.value = '';
  const removed = new Set<string>();
  try {
    for (const taskId of taskIds) {
      await deleteImageTask(taskId, controller.signal);
      removed.add(taskId);
    }
  } catch (cause) {
    if (current === version)
      removeError.value = cause instanceof Error ? cause.message : '删除失败，请重试';
  } finally {
    if (current === version) {
      tasks.value = tasks.value.filter((task) => !removed.has(task.task_id));
      removing.value = false;
      void reload();
    }
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
      <div class="image-task-actions">
        <button
          v-if="removable.length"
          type="button"
          :disabled="disabled || removing"
          @click="remove(removable.map((task) => task.task_id))"
        >
          {{ removing ? '正在清理' : '清理失败任务' }}
        </button>
        <button type="button" :disabled="loading" @click="reload()">刷新任务</button>
      </div>
    </header>
    <p v-if="removeError" class="image-error" role="status">{{ removeError }}</p>
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
        <button
          v-if="imageTaskRemovable(task)"
          type="button"
          :disabled="disabled || removing"
          :aria-label="`删除任务 ${task.prompt_preview}`"
          @click="remove([task.task_id])"
        >
          删除
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
