<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  createMemory,
  deleteMemory,
  disableMemory,
  enableMemory,
  listMemories,
  replaceMemory,
  selectMemories,
  type MemoryItem,
  type MemoryKind,
  type MemoryListParams,
  type MemoryQuery,
  type MemoryScope,
  type MemorySort,
  type MemorySelection,
} from '../api/memory'
import { composeContextPreview } from '../api/contexts'
import type { ChatRequest } from '../api/content'
import Icon from '../components/Icon.vue'

defineProps<{
  status: string
}>()

type MemoryDraft = {
  memory_id: string
  content: string
  kind: MemoryKind
  scope: MemoryScope
  scope_id: string
  tags: string
  priority: number
  relevance: number
  confidence: number
  is_enabled: boolean
}

const memoryKinds: MemoryKind[] = [
  'fact',
  'preference',
  'summary',
  'definition',
  'instruction',
  'episodic',
]
const memoryScopes: MemoryScope[] = ['global', 'user', 'session', 'context']
const sortOptions: MemorySort[] = [
  'default',
  'priority',
  'relevance',
  'confidence',
  'updated_at',
  'created_at',
  'memory_id',
]

const memories = ref<MemoryItem[]>([])
const selectedMemoryId = ref<string | null>(null)
const loading = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)
const selection = ref<MemorySelection | null>(null)
const preview = ref<ChatRequest | null>(null)
const previewContextId = ref('')
const previewModelId = ref('model-1')
const previewPrompt = ref('')

const filters = reactive({
  text: '',
  scope: '' as MemoryScope | '',
  scope_id: '',
  kind: '' as MemoryKind | '',
  tag: '',
  include_disabled: true,
  include_expired: false,
  deduplicate: true,
  sort: 'priority' as MemorySort,
})

const draft = reactive<MemoryDraft>(blankDraft())

const selectedMemory = computed(() => (
  memories.value.find((memory) => memory.memory_id === selectedMemoryId.value) || null
))
const selectedMemoryIds = computed(() => selection.value?.memories.map((memory) => memory.memory_id) || [])
const previewMemoryIds = computed(() => {
  const rawMemoryIds = preview.value?.metadata?.memory_ids
  return Array.isArray(rawMemoryIds) ? rawMemoryIds.filter((item): item is string => typeof item === 'string') : []
})
const previewMessages = computed(() => preview.value?.messages || [])

function blankDraft(): MemoryDraft {
  return {
    memory_id: `mem-${Date.now().toString(36)}`,
    content: '',
    kind: 'fact',
    scope: 'global',
    scope_id: '',
    tags: '',
    priority: 0,
    relevance: 0,
    confidence: 1,
    is_enabled: true,
  }
}

function resetDraft() {
  Object.assign(draft, blankDraft())
  selectedMemoryId.value = null
}

function editMemory(memory: MemoryItem) {
  selectedMemoryId.value = memory.memory_id
  Object.assign(draft, {
    memory_id: memory.memory_id,
    content: memory.content,
    kind: memory.kind || 'fact',
    scope: memory.scope || 'global',
    scope_id: memory.scope_id || '',
    tags: (memory.tags || []).join(', '),
    priority: memory.priority ?? 0,
    relevance: memory.relevance ?? 0,
    confidence: memory.confidence ?? 1,
    is_enabled: memory.is_enabled !== false,
  })
}

async function refreshMemories() {
  loading.value = true
  error.value = null
  try {
    memories.value = await listMemories(listParams())
    if (!selectedMemoryId.value && memories.value[0]) {
      editMemory(memories.value[0])
    } else if (selectedMemoryId.value && !memories.value.some((memory) => memory.memory_id === selectedMemoryId.value)) {
      resetDraft()
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : 'Memory request failed'
  } finally {
    loading.value = false
  }
}

async function runSelectionPreview() {
  error.value = null
  try {
    selection.value = await selectMemories(memoryQuery())
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : 'Memory selection failed'
  }
}

async function saveMemory() {
  saving.value = true
  error.value = null
  try {
    const memory = draftToMemory()
    const saved = selectedMemory.value
      ? await replaceMemory(selectedMemory.value.memory_id, memory)
      : await createMemory(memory)
    selectedMemoryId.value = saved.memory_id
    await refreshMemories()
    editMemory(saved)
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : 'Memory save failed'
  } finally {
    saving.value = false
  }
}

async function removeMemory(memory: MemoryItem) {
  if (!window.confirm(`Delete ${memory.memory_id}?`)) {
    return
  }
  error.value = null
  try {
    await deleteMemory(memory.memory_id)
    if (selectedMemoryId.value === memory.memory_id) {
      resetDraft()
    }
    await refreshMemories()
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : 'Memory delete failed'
  }
}

async function toggleMemory(memory: MemoryItem) {
  error.value = null
  try {
    const updated = memory.is_enabled === false
      ? await enableMemory(memory.memory_id)
      : await disableMemory(memory.memory_id)
    selectedMemoryId.value = updated.memory_id
    await refreshMemories()
    editMemory(updated)
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : 'Memory toggle failed'
  }
}

async function runComposePreview() {
  if (!previewContextId.value.trim()) {
    error.value = 'Context ID is required'
    return
  }
  error.value = null
  try {
    preview.value = await composeContextPreview(previewContextId.value.trim(), {
      model_id: previewModelId.value.trim() || 'model-1',
      messages: previewPrompt.value.trim()
        ? [{
          role: 'user',
          content: [{ type: 'text', text: previewPrompt.value.trim() }],
        }]
        : [],
      memory_query: memoryQuery(),
      metadata: { source: 'frontend_memory_preview' },
    })
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : 'Context preview failed'
  }
}

function listParams(): MemoryListParams {
  return {
    text: filters.text.trim(),
    scope: filters.scope,
    scope_id: filters.scope_id.trim(),
    kind: filters.kind,
    tag: filters.tag.trim(),
    include_disabled: filters.include_disabled,
    include_expired: filters.include_expired,
    deduplicate: filters.deduplicate,
    sort: filters.sort,
  }
}

function memoryQuery(): MemoryQuery {
  return {
    text: filters.text.trim() || null,
    scope: filters.scope || null,
    scope_id: filters.scope_id.trim() || null,
    kinds: filters.kind ? [filters.kind] : [],
    tags: splitTags(filters.tag),
    include_disabled: filters.include_disabled,
    include_expired: filters.include_expired,
    deduplicate: filters.deduplicate,
    sort: filters.sort,
  }
}

function draftToMemory(): MemoryItem {
  return {
    memory_id: draft.memory_id.trim(),
    content: draft.content.trim(),
    kind: draft.kind,
    scope: draft.scope,
    scope_id: draft.scope === 'global' ? null : draft.scope_id.trim(),
    tags: splitTags(draft.tags),
    priority: draft.priority,
    relevance: draft.relevance,
    confidence: draft.confidence,
    is_enabled: draft.is_enabled,
  }
}

function splitTags(value: string): string[] {
  return value
    .split(',')
    .map((tag) => tag.trim())
    .filter(Boolean)
}

function memoryTone(memory: MemoryItem): string {
  return memory.is_enabled === false ? 'danger' : 'success'
}

function messageText(message: ChatRequest['messages'][number]): string {
  return (message.content || [])
    .map((part) => part.text || part.url || part.type)
    .join('\n')
}

onMounted(() => {
  void refreshMemories()
})
</script>

<template>
  <section class="memory-workbench" aria-label="记忆库">
    <div class="memory-main">
      <div class="panel memory-toolbar">
        <div class="panel-head">
          <h2><Icon name="database" /><span>记忆库</span></h2>
          <div class="panel-head-actions">
            <span class="tag" :class="status === '已同步' ? 'success' : 'danger'">{{ status }}</span>
            <button
              class="button compact-button"
              :class="{ 'is-spinning': loading }"
              type="button"
              :disabled="loading"
              title="刷新"
              @click="refreshMemories"
            >
              <Icon name="rotate-ccw" />
              <span>{{ loading ? '刷新中' : '刷新' }}</span>
            </button>
            <button class="button compact-button primary" type="button" @click="resetDraft">
              <Icon name="plus" />
              <span>新建</span>
            </button>
          </div>
        </div>

        <div class="memory-filters">
          <label>
            <span>搜索</span>
            <input v-model="filters.text" type="search" placeholder="content / tag" @keydown.enter.prevent="refreshMemories" />
          </label>
          <label>
            <span>Scope</span>
            <select v-model="filters.scope">
              <option value="">any</option>
              <option v-for="scope in memoryScopes" :key="scope" :value="scope">{{ scope }}</option>
            </select>
          </label>
          <label>
            <span>Scope ID</span>
            <input v-model="filters.scope_id" type="text" placeholder="optional" @keydown.enter.prevent="refreshMemories" />
          </label>
          <label>
            <span>Kind</span>
            <select v-model="filters.kind">
              <option value="">any</option>
              <option v-for="kind in memoryKinds" :key="kind" :value="kind">{{ kind }}</option>
            </select>
          </label>
          <label>
            <span>Tag</span>
            <input v-model="filters.tag" type="text" placeholder="style" @keydown.enter.prevent="refreshMemories" />
          </label>
          <label>
            <span>Sort</span>
            <select v-model="filters.sort">
              <option v-for="sort in sortOptions" :key="sort" :value="sort">{{ sort }}</option>
            </select>
          </label>
          <div class="memory-filter-options">
            <label class="memory-check">
              <input v-model="filters.include_disabled" type="checkbox" />
              <span>disabled</span>
            </label>
            <label class="memory-check">
              <input v-model="filters.deduplicate" type="checkbox" />
              <span>dedupe</span>
            </label>
          </div>
          <div class="memory-filter-actions">
            <button class="button compact-button primary" type="button" @click="refreshMemories">
              <Icon name="search" />
              <span>查询</span>
            </button>
            <button class="button compact-button" type="button" @click="runSelectionPreview">
              <Icon name="list-filter" />
              <span>选择预览</span>
            </button>
          </div>
        </div>
        <p v-if="error" class="memory-error" role="alert">{{ error }}</p>
      </div>

      <div class="table-wrap memory-table">
        <table>
          <thead>
            <tr>
              <th>Memory</th>
              <th>Scope</th>
              <th>Kind</th>
              <th>Score</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="memories.length === 0">
              <td class="memory-empty-cell" colspan="6">
                <div class="memory-empty-state">
                  <Icon name="database" class="memory-empty-icon" />
                  <strong>暂无记忆</strong>
                </div>
              </td>
            </tr>
            <tr
              v-for="memory in memories"
              v-else
              :key="memory.memory_id"
              class="memory-row"
              :class="{ 'is-selected': selectedMemoryId === memory.memory_id }"
              tabindex="0"
              @click="editMemory(memory)"
              @keydown.enter.prevent="editMemory(memory)"
            >
              <td>
                <div class="memory-cell-main">
                  <strong>{{ memory.memory_id }}</strong>
                  <span>{{ memory.content }}</span>
                  <div class="memory-tags">
                    <span v-for="tag in memory.tags || []" :key="tag" class="tag">{{ tag }}</span>
                  </div>
                </div>
              </td>
              <td>
                <span>{{ memory.scope || 'global' }}</span>
                <small>{{ memory.scope_id || '' }}</small>
              </td>
              <td>{{ memory.kind || 'fact' }}</td>
              <td>
                <span>{{ memory.priority ?? 0 }}</span>
                <small>{{ memory.relevance ?? 0 }} / {{ memory.confidence ?? 1 }}</small>
              </td>
              <td>
                <span class="tag" :class="memoryTone(memory)">
                  {{ memory.is_enabled === false ? '停用' : '启用' }}
                </span>
              </td>
              <td>
                <div class="memory-actions">
                  <button class="button icon-button compact-button" type="button" title="启停" @click.stop="toggleMemory(memory)">
                    <Icon :name="memory.is_enabled === false ? 'power' : 'power-off'" />
                  </button>
                  <button class="button icon-button compact-button danger" type="button" title="删除" @click.stop="removeMemory(memory)">
                    <Icon name="trash-2" />
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <aside class="memory-side">
      <section class="panel memory-editor">
        <div class="panel-head">
          <h2><Icon name="file-pen-line" /><span>{{ selectedMemory ? '编辑记忆' : '新建记忆' }}</span></h2>
          <button class="button compact-button primary" type="button" :disabled="saving" @click="saveMemory">
            <Icon name="save" />
            <span>{{ saving ? '保存中' : '保存' }}</span>
          </button>
        </div>
        <div class="memory-form">
          <label>
            <span>ID</span>
            <input v-model="draft.memory_id" type="text" :disabled="Boolean(selectedMemory)" />
          </label>
          <label>
            <span>Kind</span>
            <select v-model="draft.kind">
              <option v-for="kind in memoryKinds" :key="kind" :value="kind">{{ kind }}</option>
            </select>
          </label>
          <label>
            <span>Scope</span>
            <select v-model="draft.scope">
              <option v-for="scope in memoryScopes" :key="scope" :value="scope">{{ scope }}</option>
            </select>
          </label>
          <label>
            <span>Scope ID</span>
            <input v-model="draft.scope_id" type="text" :disabled="draft.scope === 'global'" />
          </label>
          <label>
            <span>Tags</span>
            <input v-model="draft.tags" type="text" placeholder="style, project" />
          </label>
          <div class="memory-number-grid">
            <label>
              <span>Priority</span>
              <input v-model.number="draft.priority" type="number" />
            </label>
            <label>
              <span>Relevance</span>
              <input v-model.number="draft.relevance" min="0" max="1" step="0.1" type="number" />
            </label>
            <label>
              <span>Confidence</span>
              <input v-model.number="draft.confidence" min="0" max="1" step="0.1" type="number" />
            </label>
          </div>
          <label class="memory-switch">
            <input v-model="draft.is_enabled" type="checkbox" />
            <span>enabled</span>
          </label>
          <label class="memory-content-field">
            <span>Content</span>
            <textarea v-model="draft.content" rows="8" />
          </label>
        </div>
      </section>

      <section class="panel memory-preview">
        <div class="panel-head">
          <h2><Icon name="eye" /><span>选择与上下文</span></h2>
          <button class="button compact-button" type="button" @click="runComposePreview">
            <Icon name="scan-eye" />
            <span>预览</span>
          </button>
        </div>
        <div class="memory-preview-controls">
          <label>
            <span>Context</span>
            <input v-model="previewContextId" type="text" placeholder="ctx-1" />
          </label>
          <label>
            <span>Model</span>
            <input v-model="previewModelId" type="text" />
          </label>
          <label>
            <span>Prompt</span>
            <input v-model="previewPrompt" type="text" placeholder="optional user turn" />
          </label>
        </div>
        <div class="memory-preview-result">
          <div class="memory-selected-line">
            <span>Selection</span>
            <strong>{{ selectedMemoryIds.length }}</strong>
          </div>
          <div class="memory-id-list">
            <span v-for="memoryId in selectedMemoryIds" :key="memoryId" class="tag primary">{{ memoryId }}</span>
          </div>
          <div class="memory-selected-line">
            <span>Preview memory</span>
            <strong>{{ previewMemoryIds.length }}</strong>
          </div>
          <div class="memory-id-list">
            <span v-for="memoryId in previewMemoryIds" :key="memoryId" class="tag primary">{{ memoryId }}</span>
          </div>
          <div class="preview-messages">
            <article v-for="(message, index) in previewMessages" :key="index" class="preview-message">
              <span class="tag">{{ message.role }}</span>
              <pre>{{ messageText(message) }}</pre>
            </article>
          </div>
        </div>
      </section>
    </aside>
  </section>
</template>

<style scoped>
.memory-workbench {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(360px, 420px);
  gap: 16px;
  align-items: start;
}

.memory-main,
.memory-side {
  display: grid;
  gap: 16px;
  min-width: 0;
}

.memory-toolbar,
.memory-editor,
.memory-preview {
  min-height: 0;
}

.memory-filters,
.memory-form,
.memory-preview-controls {
  display: grid;
  gap: 12px;
}

.memory-filters {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  align-items: end;
}

.memory-filter-options,
.memory-filter-actions {
  display: flex;
  align-items: center;
  min-height: 36px;
  gap: 10px;
}

.memory-filter-options {
  grid-column: 1;
}

.memory-filter-actions {
  grid-column: 2 / -1;
  justify-content: flex-end;
}

.memory-filters label,
.memory-form label,
.memory-preview-controls label {
  display: grid;
  gap: 6px;
  min-width: 0;
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
}

.memory-filters input,
.memory-filters select,
.memory-form input,
.memory-form select,
.memory-form textarea,
.memory-preview-controls input {
  width: 100%;
  min-height: 34px;
  padding: 7px 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  color: var(--ink);
  background: var(--paper);
  font: inherit;
}

.memory-form textarea {
  resize: vertical;
  min-height: 160px;
}

.memory-check,
.memory-switch {
  grid-auto-flow: column;
  grid-auto-columns: max-content;
  align-items: center;
  gap: 8px;
}

.memory-check input,
.memory-switch input {
  width: 16px;
  min-height: 16px;
}

.memory-error {
  margin-top: 12px;
  color: var(--danger);
  font-size: 13px;
}

.memory-table {
  width: 100%;
  max-width: 100%;
  max-height: 680px;
  overflow: auto;
}

.memory-table table {
  width: 100%;
  min-width: 720px;
  border-collapse: collapse;
}

.memory-table th,
.memory-table td {
  padding: 12px;
  border-bottom: 1px solid var(--line-soft);
  text-align: left;
  vertical-align: top;
}

.memory-table th {
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
  background: var(--paper);
  position: sticky;
  top: 0;
  z-index: 1;
}

.memory-row {
  cursor: pointer;
}

.memory-row:hover,
.memory-row.is-selected {
  background: var(--soft);
}

.memory-cell-main {
  display: grid;
  gap: 6px;
  min-width: 240px;
}

.memory-cell-main strong {
  color: var(--ink);
}

.memory-cell-main span {
  max-width: 520px;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.memory-tags,
.memory-actions,
.memory-id-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.memory-table small {
  display: block;
  margin-top: 4px;
  color: var(--muted);
}

.memory-empty-cell {
  padding: 40px;
  text-align: center;
}

.memory-empty-state {
  display: inline-grid;
  gap: 8px;
  place-items: center;
}

.memory-empty-state strong {
  color: var(--ink);
}

.memory-empty-icon {
  width: 32px;
  height: 32px;
  color: var(--muted);
}

.memory-number-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.memory-content-field {
  grid-column: 1 / -1;
}

.memory-preview-result {
  display: grid;
  gap: 12px;
  margin-top: 14px;
}

.memory-selected-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--muted);
}

.memory-selected-line strong {
  color: var(--ink);
}

.preview-messages {
  display: grid;
  gap: 8px;
}

.preview-message {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--line-soft);
  border-radius: 8px;
  background: var(--soft);
}

.preview-message pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--ink);
  font: inherit;
}

@media (max-width: 1180px) {
  .memory-workbench {
    grid-template-columns: 1fr;
  }

  .memory-filters {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .memory-filters,
  .memory-number-grid {
    grid-template-columns: 1fr;
  }

  .memory-filter-options,
  .memory-filter-actions {
    grid-column: 1;
  }

  .memory-filter-actions {
    justify-content: stretch;
  }

  .memory-filter-actions .button {
    flex: 1 1 0;
  }

  .panel-head {
    align-items: flex-start;
    gap: 12px;
  }
}
</style>
