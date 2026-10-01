<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { RefreshCw, Trash2 } from '@lucide/vue'
import { deleteImageRecord, getImageRecord, listImageRecords, type ImageGenerationRecord, type ImageGenerationSummary } from '../../api'
import { useDialog } from '../common/dialog'

const props = defineProps<{ refresh: number; disabled: boolean }>()
const emit = defineEmits<{ select: [record: ImageGenerationRecord]; deleted: [recordId: string] }>()
const items = ref<ImageGenerationSummary[]>([])
const nextCursor = ref<string | undefined>()
const loading = ref(false)
const selectedId = ref('')
const readingId = ref('')
const error = ref('')
const pendingDelete = ref<ImageGenerationSummary | null>(null)
const deleting = ref(false)
const deleteError = ref('')
let listController: AbortController | null = null
let readController: AbortController | null = null
let deleteController: AbortController | null = null
let listVersion = 0
let readVersion = 0
let disposed = false

async function load(more = false): Promise<void> {
  if (more && loading.value) return
  listController?.abort()
  listController = new AbortController()
  const version = ++listVersion
  loading.value = true; error.value = ''
  try {
    const page = await listImageRecords(more ? nextCursor.value : undefined, listController.signal)
    if (version !== listVersion || disposed) return
    if (!Array.isArray(page.items)) throw new Error('历史记录加载失败')
    items.value = more ? [...items.value, ...page.items.filter(item => !items.value.some(old => old.record_id === item.record_id))] : page.items
    nextCursor.value = page.next_cursor
  } catch (cause) {
    if (version === listVersion && !disposed) error.value = cause instanceof Error ? cause.message : '历史记录加载失败'
  } finally { if (version === listVersion && !disposed) loading.value = false }
}
async function select(item: ImageGenerationSummary): Promise<void> {
  if (props.disabled) return
  readController?.abort(); readController = new AbortController()
  const version = ++readVersion
  readingId.value = item.record_id; error.value = ''
  try {
    const record = await getImageRecord(item.record_id, readController.signal)
    if (version !== readVersion || props.disabled || disposed) return
    selectedId.value = item.record_id; emit('select', record)
  } catch (cause) {
    if (version === readVersion && !disposed) error.value = cause instanceof Error ? cause.message : '读取图片失败'
  } finally { if (version === readVersion && !disposed) readingId.value = '' }
}
function closeDelete(): void { if (!deleting.value) pendingDelete.value = null }
const dialog = useDialog(() => pendingDelete.value !== null, closeDelete)
function confirmDelete(item: ImageGenerationSummary): void { pendingDelete.value = item; deleteError.value = '' }
async function remove(): Promise<void> {
  if (!pendingDelete.value || deleting.value || props.disabled) return
  const id = pendingDelete.value.record_id
  deleteController = new AbortController(); deleting.value = true
  try {
    await deleteImageRecord(id, deleteController.signal)
    if (disposed) return
    // Invalidate detail requests so deleted images cannot reappear from a late response.
    readVersion++; readController?.abort(); readingId.value = ''
    pendingDelete.value = null; items.value = items.value.filter(item => item.record_id !== id)
    if (selectedId.value === id) selectedId.value = ''
    emit('deleted', id)
    await load()
  } catch (cause) {
    if (!disposed) deleteError.value = cause instanceof Error ? cause.message : '删除失败，请重试'
  } finally { if (!disposed) deleting.value = false }
}
watch(() => props.refresh, () => { selectedId.value = ''; void load() }, { immediate: true })
watch(() => props.disabled, disabled => {
  if (disabled) { readVersion++; readController?.abort(); readingId.value = '' }
})
onBeforeUnmount(() => {
  disposed = true; listController?.abort(); readController?.abort(); deleteController?.abort()
})
</script>

<template>
  <section class="image-history" aria-label="生成历史">
    <header><h2>生成历史</h2><button class="icon-button" title="刷新生成历史" aria-label="刷新生成历史" :disabled="loading" @click="load()"><RefreshCw :size="18" /></button></header>
    <p v-if="error" class="image-error" role="alert">{{ error }}</p>
    <p v-if="loading" class="image-muted" role="status">正在加载记录…</p>
    <p v-else-if="!items.length && !error" class="image-muted">暂无生成记录</p>
    <ul class="image-history-list"><li v-for="item in items" :key="item.record_id">
      <button type="button" class="image-history-record" :aria-label="`查看生成记录 ${item.prompt_preview}`" :aria-pressed="selectedId === item.record_id" :disabled="disabled || deleting" @click="select(item)">
        <strong>{{ item.prompt_preview }}</strong><span class="image-muted">{{ item.model_id }} · {{ item.provider_id }} · {{ item.image_count }} 张<span v-if="!item.archived"> · 部分图片未归档</span><span v-if="readingId === item.record_id"> · 正在读取</span></span>
      </button>
      <time :datetime="item.created_at" class="image-muted">{{ new Date(item.created_at).toLocaleString() }}</time>
      <button class="icon-button" type="button" title="删除生成记录" :aria-label="`删除生成记录 ${item.prompt_preview}`" :disabled="disabled || deleting" @click="confirmDelete(item)"><Trash2 :size="17" /></button>
    </li></ul>
    <button v-if="nextCursor" type="button" :disabled="loading" @click="load(true)">加载更多记录</button>
  </section>
  <dialog :ref="dialog.setDialog" class="chat-confirm-dialog" aria-labelledby="delete-image-title" @cancel="dialog.onCancel" @click="dialog.onBackdropClick" @keydown="dialog.onKeydown">
    <h2 id="delete-image-title">删除生成记录？</h2>
    <p>{{ pendingDelete?.prompt_preview }}</p><p>这条记录及其保存的 {{ pendingDelete?.image_count }} 张图片将被删除。</p>
    <p v-if="deleteError" class="image-error" role="alert">{{ deleteError }}</p>
    <div class="chat-confirm-actions"><button type="button" :disabled="deleting" autofocus @click="closeDelete">取消</button><button type="button" class="chat-delete-confirm" :disabled="deleting || disabled" @click="remove">{{ deleting ? '正在删除' : '删除记录' }}</button></div>
  </dialog>
</template>
