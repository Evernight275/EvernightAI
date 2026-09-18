<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { createMemory, listMemories, getMemory, replaceMemory, enableMemory, disableMemory, deleteMemory, selectMemories, type MemoryItem, type MemoryKind, type MemoryScope } from '../../api/memory'
const emit = defineEmits<{ changed: [] }>()
const items = ref<MemoryItem[]>([])
const text = ref('')
const busy = ref(false)
const error = ref('')
const notice = ref('')
const editing = ref<MemoryItem | null>(null)
const content = ref('')
const kind = ref<MemoryKind>('fact')
const scope = ref<MemoryScope>('global')
const scopeId = ref('')
const tags = ref('')
const pendingDelete = ref<MemoryItem | null>(null)
const kinds: Record<MemoryKind, string> = { fact: '事实', preference: '偏好', summary: '摘要', definition: '定义', instruction: '指令', episodic: '事件' }
async function load() { items.value = await listMemories({ text: text.value, include_disabled: true, include_expired: true }) }
async function perform(action: () => Promise<void>) {
  if (busy.value) return
  busy.value = true; error.value = ''; notice.value = ''
  try { await action() } catch (cause) { error.value = cause instanceof Error ? cause.message : '操作失败' }
  finally { busy.value = false }
}
function reset() { editing.value = null; content.value = ''; kind.value = 'fact'; scope.value = 'global'; scopeId.value = ''; tags.value = '' }
async function edit(item: MemoryItem) {
  await perform(async () => {
    const current = await getMemory(item.memory_id)
    editing.value = current; content.value = current.content; kind.value = current.kind || 'fact'
    scope.value = current.scope || 'global'; scopeId.value = current.scope_id || ''; tags.value = current.tags?.join(', ') || ''
  })
}
async function save() {
  await perform(async () => {
    const item: MemoryItem = { ...editing.value, memory_id: editing.value?.memory_id || crypto.randomUUID(),
      content: content.value.trim(), kind: kind.value, scope: scope.value,
      scope_id: scope.value === 'global' ? null : scopeId.value.trim(), tags: tags.value.split(',').map(tag => tag.trim()).filter(Boolean) }
    if (editing.value) await replaceMemory(item.memory_id, item)
    else await createMemory(item)
    reset(); emit('changed'); await load(); notice.value = '记忆已保存'
  })
}
async function toggle(item: MemoryItem) {
  await perform(async () => {
    if (item.is_enabled === false) await enableMemory(item.memory_id)
    else await disableMemory(item.memory_id)
    emit('changed'); await load()
  })
}
async function remove() {
  if (!pendingDelete.value) return
  const id = pendingDelete.value.memory_id
  await perform(async () => { await deleteMemory(id); pendingDelete.value = null; if (editing.value?.memory_id === id) reset(); emit('changed'); await load() })
}
onMounted(() => perform(load))
</script>

<template>
  <section class="settings-manager" aria-label="记忆管理">
    <form class="settings-toolbar" @submit.prevent="perform(load)">
      <input v-model="text" type="search" aria-label="搜索记忆" placeholder="搜索记忆" />
      <button :disabled="busy">搜索</button>
      <button type="button" :disabled="busy" @click="perform(async () => { const selected = await selectMemories({ text }); items = selected.memories; notice = '显示策略选中的记忆' })">预览选择</button>
    </form>
    <p v-if="error" role="alert">{{ error }}</p><p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="busy" role="status">正在处理…</p>
    <p v-else-if="!items.length" class="settings-help">没有匹配的记忆。</p>
    <div v-for="item in items" :key="item.memory_id" class="settings-row">
      <div><h3>{{ kinds[item.kind || 'fact'] }} · {{ item.is_enabled === false ? '已停用' : '已启用' }}</h3><p>{{ item.content }}</p><p>{{ item.scope }} {{ item.scope_id }} · {{ item.tags?.join('、') }}</p></div>
      <div class="settings-inline-actions"><button :disabled="busy" @click="edit(item)">编辑</button><button :disabled="busy" @click="toggle(item)">{{ item.is_enabled === false ? '启用' : '停用' }}</button><button :disabled="busy" @click="pendingDelete = item">删除</button></div>
    </div>
    <div v-if="pendingDelete" class="settings-confirm" role="group" aria-label="删除记忆确认"><p>永久删除这条记忆？{{ pendingDelete.content }}</p><button :disabled="busy" @click="pendingDelete = null">取消</button><button :disabled="busy" @click="remove">确认删除记忆</button></div>
    <form class="settings-form" @submit.prevent="save">
      <h3>{{ editing ? '编辑记忆' : '添加记忆' }}</h3>
      <fieldset :disabled="busy">
        <label>记忆内容<textarea v-model="content" required rows="3" /></label>
        <label>记忆类型<select v-model="kind"><option v-for="(label, value) in kinds" :key="value" :value="value">{{ label }}</option></select></label>
        <label>作用范围<select v-model="scope"><option value="global">全局</option><option value="user">用户</option><option value="session">会话</option><option value="context">上下文</option></select></label>
        <label v-if="scope !== 'global'">范围标识<input v-model="scopeId" required /></label>
        <label>标签<input v-model="tags" placeholder="用逗号分隔" /></label>
        <div class="settings-inline-actions"><button class="button-primary">保存记忆</button><button v-if="editing" type="button" @click="reset">取消编辑</button></div>
      </fieldset>
    </form>
  </section>
</template>
