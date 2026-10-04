import { onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { getImageTask, listImageTasks, type ImageTask, type ImageTaskStatus } from '../api/images';
import { authGeneration } from './workspaceRuntime';

export const imageTaskLabels: Record<ImageTaskStatus, string> = {
  queued: '排队中',
  running: '正在生成',
  succeeded: '已完成',
  failed: '失败',
  interrupted: '已中断',
};
export function imageTaskActive(task: ImageTask): boolean {
  return task.status === 'queued' || task.status === 'running';
}
function pause(ms: number, signal: AbortSignal): Promise<void> {
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer);
      reject(new DOMException('Aborted', 'AbortError'));
    };
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', abort);
      resolve();
    }, ms);
    signal.addEventListener('abort', abort, { once: true });
  });
}
export async function waitForImageTask(
  task: ImageTask,
  signal: AbortSignal,
  progress: (task: ImageTask) => void,
): Promise<ImageTask> {
  let current = task;
  progress(current);
  while (imageTaskActive(current)) {
    await pause(1000, signal);
    current = await getImageTask(current.task_id, signal);
    progress(current);
  }
  return current;
}

export function useImageTasks(sessionId: () => string | undefined = () => undefined) {
  const tasks = shallowRef<ImageTask[]>([]);
  const error = ref('');
  const loading = ref(false);
  const cursor = ref<string>();
  let controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let version = 0;
  let currentLoad = false;
  let pages = 1;
  async function reload(more = false): Promise<void> {
    if (currentLoad) return;
    currentLoad = true;
    loading.value = true;
    const current = version;
    try {
      let position = more ? cursor.value : undefined;
      let items: ImageTask[] = [];
      const count = more ? 1 : pages;
      let loaded = 0;
      for (let index = 0; index < count; index++) {
        const page = await listImageTasks(sessionId(), position, controller.signal);
        if (current !== version) return;
        if (!Array.isArray(page.items)) throw new Error('无法读取图片任务');
        items.push(...page.items);
        position = page.next_cursor;
        loaded++;
        if (!position) break;
      }
      if (current !== version) return;
      tasks.value = more
        ? [
            ...tasks.value,
            ...items.filter((item) => !tasks.value.some((old) => old.task_id === item.task_id)),
          ]
        : items;
      pages = more ? pages + 1 : loaded;
      cursor.value = position;
      error.value = '';
    } catch (cause) {
      if (current === version && !controller.signal.aborted)
        error.value = cause instanceof Error ? cause.message : '无法读取图片任务';
    } finally {
      if (current === version) {
        currentLoad = false;
        loading.value = false;
        clearTimeout(timer);
        timer = setTimeout(() => void reload(), 2500);
      }
    }
  }
  function reset() {
    version++;
    controller.abort();
    controller = new AbortController();
    clearTimeout(timer);
    currentLoad = false;
    pages = 1;
    tasks.value = [];
    cursor.value = undefined;
    error.value = '';
    void reload();
  }
  watch([authGeneration, sessionId], reset, { immediate: true, flush: 'sync' });
  onBeforeUnmount(() => {
    version++;
    controller.abort();
    clearTimeout(timer);
  });
  return { tasks, error, loading, cursor, reload };
}
