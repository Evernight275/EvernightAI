import { onUnmounted, reactive, ref, watch } from 'vue';
import { readFileArtifact, uploadFileArtifact, type FileArtifactInfo } from '../../api/files';
import { authGeneration } from '../../runtime/workspaceRuntime';

export const imageMaxBytes = 20 * 1024 * 1024;
export const imageTotalMaxBytes = 50 * 1024 * 1024;
export const imageMaxCount = 10;
const imageTypes = new Set(['image/png', 'image/jpeg', 'image/webp']);

export type ChatAttachment = {
  artifact: FileArtifactInfo;
  previewUrl: string;
  status: 'ready' | 'loading' | 'error';
  error: string;
  file?: File;
};

export function useChatAttachments(sessionKey: () => string, busy: () => boolean) {
  const attachments = ref<ChatAttachment[]>([]);
  const error = ref('');
  const uploading = ref(false);
  const operations = new Map<ChatAttachment, AbortController>();
  let generation = 0;
  let queue = Promise.resolve();
  let activeItem: ChatAttachment | null = null;
  const objectUrls = new Set<string>();
  const persistKey = () => `evernight.chatDraft.${sessionKey()}`;
  const authEvents = ['evernight-api-key-change', 'evernight-access-token-change'];

  function revoke(url: string): void {
    if (!url) return;
    URL.revokeObjectURL(url);
    objectUrls.delete(url);
  }
  function clear(clearDraftRefs = false): void {
    generation++;
    operations.forEach((operation) => operation.abort());
    operations.clear();
    queue = Promise.resolve();
    activeItem = null;
    uploading.value = false;
    attachments.value.forEach((item) => revoke(item.previewUrl));
    attachments.value = [];
    error.value = '';
    if (clearDraftRefs) persist();
  }
  async function addFiles(files: FileList | File[]): Promise<void> {
    if (busy()) return;
    error.value = '';
    const accepted: File[] = [];
    let plannedBytes = attachments.value.reduce((sum, item) => sum + item.artifact.size_bytes, 0);
    for (const file of Array.from(files)) {
      if (!imageTypes.has(file.type)) {
        error.value = '仅支持 PNG、JPEG 或 WebP 图片。';
      } else if (file.size > imageMaxBytes) {
        error.value = '单张图片不能超过 20 MiB。';
      } else if (attachments.value.length + accepted.length >= imageMaxCount) {
        error.value = '最多添加 10 张图片。';
      } else if (plannedBytes + file.size > imageTotalMaxBytes) {
        error.value = '图片总大小不能超过 50 MiB。';
      } else {
        accepted.push(file);
        plannedBytes += file.size;
      }
    }
    for (const file of accepted) {
      const item = makePendingAttachment(file);
      attachments.value.push(item);
      queue = queue.then(() => upload(file, item));
    }
    await queue;
  }
  function makePendingAttachment(file: File): ChatAttachment {
    const url = URL.createObjectURL(file);
    objectUrls.add(url);
    return reactive<ChatAttachment>({
      artifact: {
        artifact_id: `uploading-${Date.now()}-${Math.random()}`,
        name: file.name,
        title: file.name,
        mime_type: file.type,
        size_bytes: file.size,
        preview_kind: 'image',
        created_at: new Date().toISOString(),
      },
      previewUrl: url,
      status: 'loading',
      error: '',
      file,
    });
  }
  async function upload(file: File, item: ChatAttachment): Promise<void> {
    if (!attachments.value.includes(item)) return;
    const current = generation;
    const aborter = new AbortController();
    operations.set(item, aborter);
    activeItem = item;
    uploading.value = true;
    try {
      const artifact = await uploadFileArtifact(file, file.name, aborter.signal);
      if (current !== generation || aborter.signal.aborted) return;
      const url = URL.createObjectURL(file);
      objectUrls.add(url);
      item.artifact = artifact;
      revoke(item.previewUrl);
      item.previewUrl = url;
      item.status = 'ready';
    } catch (cause) {
      if (current !== generation || aborter.signal.aborted) return;
      const message = cause instanceof Error ? cause.message : '图片上传失败';
      item.status = 'error';
      item.error = message;
    } finally {
      if (operations.get(item) === aborter) operations.delete(item);
      if (current === generation) {
        uploading.value = false;
        activeItem = null;
        persist();
      }
    }
  }
  async function retry(index: number): Promise<void> {
    const item = attachments.value[index];
    if (!item || busy()) return;
    if (item.file) {
      item.status = 'loading';
      item.error = '';
      queue = queue.then(() => upload(item.file!, item));
      await queue;
      return;
    }
    item.status = 'loading';
    item.error = '';
    const current = generation;
    const aborter = new AbortController();
    operations.get(item)?.abort();
    operations.set(item, aborter);
    try {
      const blob = await readFileArtifact(item.artifact.artifact_id, aborter.signal);
      if (current !== generation || aborter.signal.aborted) return;
      const url = URL.createObjectURL(blob);
      objectUrls.add(url);
      revoke(item.previewUrl);
      item.previewUrl = url;
      item.artifact = { ...item.artifact, size_bytes: blob.size, mime_type: blob.type };
      item.status = 'ready';
    } catch (cause) {
      if (current === generation && !aborter.signal.aborted) {
        item.status = 'error';
        item.error = cause instanceof Error ? cause.message : '无法载入图片';
      }
    } finally {
      if (operations.get(item) === aborter) operations.delete(item);
    }
    if (current === generation && !aborter.signal.aborted) persist();
  }
  function remove(index: number): void {
    const [item] = attachments.value.splice(index, 1);
    if (item) {
      operations.get(item)?.abort();
      operations.delete(item);
      if (activeItem === item) {
        activeItem = null;
        uploading.value = false;
      }
      revoke(item.previewUrl);
    }
    persist();
  }
  function persist(): void {
    try {
      const saved = attachments.value
        .filter(
          (item) =>
            item.artifact.artifact_id && !item.artifact.artifact_id.startsWith('uploading-'),
        )
        .map(({ artifact }) => artifact);
      const draft = JSON.parse(sessionStorage.getItem(persistKey()) || '{}');
      sessionStorage.setItem(persistKey(), JSON.stringify({ ...draft, attachments: saved }));
    } catch {
      // Drafts remain usable if browser storage is unavailable.
    }
  }
  async function restore(): Promise<void> {
    clear();
    let artifacts: FileArtifactInfo[] = [];
    try {
      const saved = JSON.parse(sessionStorage.getItem(persistKey()) || 'null');
      if (Array.isArray(saved?.attachments)) artifacts = saved.attachments;
    } catch {
      return;
    }
    await setArtifacts(artifacts);
  }
  async function setArtifacts(artifacts: FileArtifactInfo[]): Promise<void> {
    clear();
    const current = generation;
    await Promise.all(
      artifacts.slice(0, imageMaxCount).map(async (artifact) => {
        if (!artifact || typeof artifact.artifact_id !== 'string') return;
        const item = reactive<ChatAttachment>({
          artifact,
          previewUrl: '',
          status: 'loading',
          error: '',
        });
        attachments.value.push(item);
        const restoreController = new AbortController();
        operations.set(item, restoreController);
        try {
          const blob = await readFileArtifact(artifact.artifact_id, restoreController.signal);
          if (generation !== current || restoreController.signal.aborted) return;
          item.artifact = { ...artifact, size_bytes: blob.size, mime_type: blob.type };
          item.previewUrl = URL.createObjectURL(blob);
          objectUrls.add(item.previewUrl);
          item.status = 'ready';
        } catch (cause) {
          if (generation !== current || restoreController.signal.aborted) return;
          item.status = 'error';
          item.error = cause instanceof Error ? cause.message : '无法载入图片';
        } finally {
          if (operations.get(item) === restoreController) operations.delete(item);
        }
      }),
    );
  }
  watch(sessionKey, () => void restore(), { immediate: true, flush: 'post' });
  watch(authGeneration, () => clear(true), { flush: 'sync' });
  const authChanged = () => clear(true);
  if (typeof window !== 'undefined')
    authEvents.forEach((name) => window.addEventListener(name, authChanged));
  onUnmounted(() => {
    clear();
    if (typeof window !== 'undefined')
      authEvents.forEach((name) => window.removeEventListener(name, authChanged));
    objectUrls.forEach((url) => URL.revokeObjectURL(url));
    objectUrls.clear();
  });
  return { attachments, error, uploading, addFiles, remove, retry, clear, persist, setArtifacts };
}
