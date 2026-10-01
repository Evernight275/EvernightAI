<script setup lang="ts">
import { ref, watch } from 'vue'
import { Download, Pencil, Plus, Save, Upload, X } from '@lucide/vue'
import { createSkill, deleteSkill, getSkillTemplate, updateSkill, type SkillCapability, type SkillDefinition, type SkillTemplateConfig } from '../../api/skills'
import type { ToolDefinition } from '../../api/tools'
import SkillVariablesEditor from '../skills/SkillVariablesEditor.vue'
import SkillPreview from '../skills/SkillPreview.vue'
const props = defineProps<{ skills: SkillDefinition[]; tools: ToolDefinition[] }>()
const emit = defineEmits<{ changed: [] }>()
const editing = ref<string | null>(null)
const editor = ref<SkillTemplateConfig | null>(null)
const schemaText = ref('{}')
const toolsText = ref('')
const variables = ref('{}')
const previewSkill = ref<SkillDefinition | null>(null)
const busy = ref(false)
const error = ref('')
const feedback = ref('')
const pendingDelete = ref<string | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const capabilities: SkillCapability[] = ['agent', 'chat', 'tool_use', 'context', 'memory', 'streaming']
watch(() => props.skills, () => {
  if (previewSkill.value) previewSkill.value = props.skills.find(skill => skill.name === previewSkill.value?.name) || null
})
function setEditor(config: SkillTemplateConfig, name: string | null) {
  editor.value = structuredClone(config); editing.value = name
  schemaText.value = JSON.stringify(config.input_schema || {}, null, 2)
  toolsText.value = (config.required_tools || []).join(', ')
  error.value = ''; feedback.value = ''; previewSkill.value = null; pendingDelete.value = null
}
function add() {
  setEditor({ name: '', description: '', prompt: '', capabilities: ['agent', 'chat'], is_enabled: true, input_schema: { type: 'object', properties: {} } }, null)
}
async function edit(skill: SkillDefinition) {
  busy.value = true; error.value = ''
  try { setEditor(await getSkillTemplate(skill.name), skill.name) }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '技能加载失败' }
  finally { busy.value = false }
}
async function save() {
  if (!editor.value || busy.value) return
  busy.value = true; error.value = ''; feedback.value = ''
  try {
    const inputSchema: unknown = JSON.parse(schemaText.value)
    if (!inputSchema || typeof inputSchema !== 'object' || Array.isArray(inputSchema)) throw new Error('参数 schema 必须是 JSON 对象')
    const config = { ...editor.value, name: editor.value.name.trim(), description: editor.value.description.trim(),
      input_schema: inputSchema as Record<string, unknown>, required_tools: [...new Set(toolsText.value.split(',').map(name => name.trim()).filter(Boolean))] }
    if (editing.value) { const { name, is_template, ...update } = config; await updateSkill(name, update) }
    else await createSkill(config)
    editor.value = null; previewSkill.value = null; feedback.value = '技能已保存'; emit('changed')
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '技能保存失败' }
  finally { busy.value = false }
}
async function toggle(skill: SkillDefinition) {
  busy.value = true; error.value = ''; feedback.value = ''
  try { await updateSkill(skill.name, { is_enabled: skill.is_enabled === false }); previewSkill.value = null; emit('changed') }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '技能状态更新失败' }
  finally { busy.value = false }
}
async function remove() {
  if (!pendingDelete.value || busy.value) return
  busy.value = true; error.value = ''
  try { await deleteSkill(pendingDelete.value); pendingDelete.value = null; previewSkill.value = null; feedback.value = '技能已删除'; emit('changed') }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '技能删除失败' }
  finally { busy.value = false }
}
async function load(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  busy.value = true; error.value = ''
  try {
    if (file.size > 1_000_000) throw new Error('模板文件不能超过 1 MB')
    const config: unknown = JSON.parse(await file.text())
    if (!config || typeof config !== 'object' || Array.isArray(config)) throw new Error('模板必须是 JSON 对象')
    const template = config as SkillTemplateConfig
    if (typeof template.name !== 'string' || typeof template.description !== 'string' || typeof template.prompt !== 'string') throw new Error('模板需要 name、description 和 prompt')
    if (template.capabilities !== undefined && (!Array.isArray(template.capabilities) || template.capabilities.some(value => !capabilities.includes(value)))) throw new Error('模板能力声明无效')
    if (template.required_tools !== undefined && (!Array.isArray(template.required_tools) || template.required_tools.some(value => typeof value !== 'string'))) throw new Error('模板工具声明必须是字符串数组')
    if (template.is_enabled !== undefined && typeof template.is_enabled !== 'boolean') throw new Error('模板启用状态必须是布尔值')
    if (template.input_schema != null && (typeof template.input_schema !== 'object' || Array.isArray(template.input_schema))) throw new Error('参数 schema 必须是 JSON 对象')
    template.capabilities ||= ['agent', 'chat']; template.is_enabled ??= true
    setEditor(template, null)
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '模板导入失败' }
  finally { busy.value = false; input.value = '' }
}
async function download(skill: SkillDefinition) {
  busy.value = true; error.value = ''
  try {
    const config = await getSkillTemplate(skill.name)
    const url = URL.createObjectURL(new Blob([JSON.stringify(config, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a'); link.href = url; link.download = `${skill.name}.json`; link.click(); URL.revokeObjectURL(url)
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '模板导出失败' }
  finally { busy.value = false }
}
</script>

<template>
  <section class="settings-manager skill-settings" aria-label="技能管理">
    <div class="settings-toolbar">
      <button type="button" :disabled="busy" @click="add"><Plus :size="16" />新建技能</button>
      <button type="button" :disabled="busy" @click="fileInput?.click()"><Upload :size="16" />导入模板</button>
      <input ref="fileInput" type="file" accept="application/json,.json" hidden aria-label="导入技能模板" @change="load" />
    </div>
    <p v-if="error" role="alert">{{ error }}</p><p v-if="feedback" role="status">{{ feedback }}</p>
    <p v-if="!skills.length" class="settings-help">暂无技能</p>
    <div v-for="skill in skills" :key="skill.name" class="settings-row">
      <div><h3>{{ skill.name }} · {{ skill.is_enabled === false ? '已停用' : '已启用' }}</h3><p>{{ skill.description }}</p>
        <p>{{ skill.capabilities?.join('、') || '无能力声明' }}</p><p>必需工具：{{ skill.required_tools?.join('、') || '无' }}</p>
        <p v-if="skill.required_tools?.some(name => !tools.some(tool => tool.name === name))">部分必需工具不可用</p>
      </div>
      <div class="settings-inline-actions">
        <button v-if="skill.is_template" type="button" :disabled="busy" :aria-label="`编辑技能 ${skill.name}`" :title="`编辑技能 ${skill.name}`" @click="edit(skill)"><Pencil :size="16" /></button>
        <button v-if="skill.is_template" type="button" :disabled="busy" :aria-label="`${skill.is_enabled === false ? '启用' : '停用'} ${skill.name}`" @click="toggle(skill)">{{ skill.is_enabled === false ? '启用' : '停用' }}</button>
        <button type="button" :disabled="busy || skill.is_enabled === false" :aria-label="`预览技能 ${skill.name}`" @click="previewSkill = skill; variables = '{}'">预览</button>
        <button v-if="skill.is_template" type="button" :disabled="busy" :aria-label="`导出技能 ${skill.name}`" :title="`导出技能 ${skill.name}`" @click="download(skill)"><Download :size="16" /></button>
        <button v-if="skill.is_template" type="button" :disabled="busy" :aria-label="`删除技能 ${skill.name}`" @click="pendingDelete = skill.name">删除</button>
        <span v-else class="settings-help">内置技能</span>
      </div>
    </div>
    <div v-if="pendingDelete" class="settings-confirm"><p>删除技能 {{ pendingDelete }}？</p><button type="button" :disabled="busy" @click="pendingDelete = null">取消</button><button type="button" :disabled="busy" @click="remove">确认删除技能</button></div>
    <section v-if="previewSkill" aria-label="技能参数预览">
      <h3>{{ previewSkill.name }}</h3>
      <SkillVariablesEditor :key="previewSkill.name" v-model="variables" :schema="previewSkill.input_schema" :disabled="busy" />
      <SkillPreview :skill="skills.find(skill => skill.name === previewSkill?.name) || previewSkill" :variables="variables" :disabled="busy" />
    </section>
    <form v-if="editor" class="settings-form" aria-label="技能模板编辑" @submit.prevent="save">
      <fieldset :disabled="busy">
        <label>技能名称<input v-model="editor.name" required maxlength="128" pattern="[A-Za-z][A-Za-z0-9_.-]*" :disabled="!!editing" /></label>
        <label>技能描述<input v-model="editor.description" required maxlength="2000" /></label>
        <label>提示词模板<textarea v-model="editor.prompt" rows="6" required maxlength="65536" placeholder="例如：Use $tone style. Literal dollar: $$" /></label>
        <label>参数 Schema（JSON）<textarea v-model="schemaText" rows="6" /></label>
        <div class="skill-capabilities" role="group" aria-label="技能能力"><label v-for="capability in capabilities" :key="capability" class="settings-checkbox"><input v-model="editor.capabilities" type="checkbox" :value="capability" />{{ capability }}</label></div>
        <label>必需工具<input v-model="toolsText" placeholder="read_text_file, write_text_file" /></label>
        <label class="settings-checkbox"><input v-model="editor.is_enabled" type="checkbox" />启用技能</label>
        <div class="settings-inline-actions"><button class="button-primary" type="submit"><Save :size="16" />保存技能</button><button type="button" @click="editor = null"><X :size="16" />取消编辑</button></div>
      </fieldset>
    </form>
  </section>
</template>

<style scoped>
.skill-settings button { display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 7px 12px; border-radius: 20px; }
.skill-settings h3 { font-size: 14px; }
.skill-settings section { border-bottom: 1px solid var(--color-border); padding: 16px 0; overflow-wrap: anywhere; }
.skill-capabilities { display: flex; flex-wrap: wrap; gap: 12px; }
.skill-settings input[hidden] { display: none; }
</style>
