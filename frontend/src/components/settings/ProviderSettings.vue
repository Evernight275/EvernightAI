<script setup lang="ts">
import { ref } from 'vue'
import { Pencil, Plus, Save, X } from '@lucide/vue'
import { createProvider, deleteProvider, getProviderConfig, updateProvider, type ProviderInfo, type ProviderConfigView, type ProviderConfigUpdate, type ProviderType, type ProviderModelCapability, type ProviderModelConfig } from '../../api/providers'
import type { ProviderCatalog } from '../../domain/workspace'
const props = defineProps<{ catalog: ProviderCatalog }>()
const emit = defineEmits<{ changed: [] }>()
const name = ref('')
const providerId = ref('')
const type = ref<ProviderType>('openai')
const baseUrl = ref('')
const apiKey = ref('')
const modelIds = ref('')
const discover = ref(false)
const capabilities = ref<ProviderModelCapability[]>(['chat'])
const capabilityLabels: Record<ProviderModelCapability, string> = { chat: '聊天', tool_call: '工具调用', image_recognition: '图像识别', image_generation: '图像生成', video_recognition: '视频识别', video_generation: '视频生成' }
const pendingDelete = ref<string | null>(null)
const busy = ref(false)
const error = ref('')
const feedback = ref('')
const editing = ref<ProviderConfigView | null>(null)
const credentialMode = ref<'keep' | 'key' | 'reference' | 'clear'>('keep')
const secretRef = ref('')
const editorOpen = ref(false)
const modelEntries = ref<{ key: string; config: ProviderModelConfig }[]>([])

function reset() {
  editing.value = null; name.value = ''; providerId.value = ''; baseUrl.value = ''; apiKey.value = ''; modelIds.value = ''
  secretRef.value = ''; credentialMode.value = 'keep'; modelEntries.value = []
  type.value = 'openai'; discover.value = false; capabilities.value = ['chat']
}

async function edit(id: string) {
  if (busy.value) return
  busy.value = true; error.value = ''; feedback.value = ''
  try {
    const config = await getProviderConfig(id)
    reset(); editing.value = config; providerId.value = config.provider_id; name.value = config.name; type.value = config.type
    baseUrl.value = config.base_url || ''; discover.value = config.discover_models || false; secretRef.value = config.api_key_secret_ref || ''
    modelEntries.value = Object.entries(config.model || {}).map(([key, model]) => ({ key, config: { ...model, capabilities: [...(model.capabilities || [])] } }))
    pendingDelete.value = null; editorOpen.value = true
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '配置加载失败' }
  finally { busy.value = false }
}

function updatedModels(): Record<string, ProviderModelConfig> {
  const models: [string, ProviderModelConfig][] = []
  const keys = new Set<string>()
  for (const entry of modelEntries.value) {
    const id = entry.config.model_id.trim()
    const key = entry.key || id
    if (!id) throw new Error('模型 ID 不能为空')
    if (keys.has(key)) throw new Error('模型标识重复')
    keys.add(key); models.push([key, { ...entry.config, model_id: id }])
  }
  return Object.fromEntries(models)
}

async function save() {
  if (busy.value) return
  busy.value = true; error.value = ''; feedback.value = ''
  try {
    if (!name.value.trim()) throw new Error('服务名称不能为空')
    if (editing.value) {
      const update: ProviderConfigUpdate = { name: name.value.trim(), type: type.value, base_url: baseUrl.value.trim() || null, discover_models: discover.value, model: updatedModels() }
      if (credentialMode.value === 'key') {
        if (!apiKey.value.trim()) throw new Error('请输入新的服务密钥')
        update.api_key = apiKey.value
      } else if (credentialMode.value === 'reference') {
        if (!secretRef.value.trim()) throw new Error('请输入密钥引用')
        update.api_key_secret_ref = secretRef.value.trim()
      } else if (credentialMode.value === 'clear') {
        update.api_key = null; update.api_key_secret_ref = null
      }
      await updateProvider(editing.value.provider_id, update)
      feedback.value = '模型服务已更新'
    } else {
      if (props.catalog.providers.some(item => item.provider_id === providerId.value.trim())) throw new Error('此服务标识已存在，请使用新的标识')
      const ids = [...new Set(modelIds.value.split(/[,\n]/).map(id => id.trim()).filter(Boolean))]
      await createProvider({ provider_id: providerId.value.trim(), name: name.value.trim(), type: type.value,
        base_url: baseUrl.value.trim() || null, api_key: apiKey.value || null, discover_models: discover.value,
        model: Object.fromEntries(ids.map(model_id => [model_id, { model_id, capabilities: [...capabilities.value] }])),
      })
      feedback.value = '模型服务已添加'
    }
    reset(); editorOpen.value = false; emit('changed')
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '保存失败' }
  finally { busy.value = false }
}
async function remove() {
  if (!pendingDelete.value) return
  busy.value = true; error.value = ''
  try { await deleteProvider(pendingDelete.value); if (editing.value?.provider_id === pendingDelete.value) { reset(); editorOpen.value = false }; pendingDelete.value = null; feedback.value = '模型服务已删除'; emit('changed') }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '删除失败' }
  finally { busy.value = false }
}

async function toggleEnabled(provider: ProviderInfo) {
  if (busy.value) return
  busy.value = true; error.value = ''; feedback.value = ''
  const enabled = provider.is_enabled === false
  try {
    await updateProvider(provider.provider_id, { is_enabled: enabled })
    if (editing.value?.provider_id === provider.provider_id) editing.value.is_enabled = enabled
    feedback.value = enabled ? '模型服务已启用' : '模型服务已停用'
    emit('changed')
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '服务状态更新失败' }
  finally { busy.value = false }
}
</script>

<template>
  <section class="settings-manager" aria-label="模型服务管理">
    <div v-for="provider in catalog.providers" :key="provider.provider_id" class="settings-row">
      <div><h3>{{ provider.name }}</h3><p>{{ provider.type }} · {{ provider.is_enabled === false ? '已停用' : '已启用' }}</p>
        <p>{{ catalog.modelGroups.find(group => group.provider.provider_id === provider.provider_id)?.models.map(model => model.model_id).join('、') || '未声明模型' }}</p></div>
      <div class="settings-inline-actions">
        <button class="provider-icon-button" type="button" :disabled="busy" :aria-label="`编辑服务 ${provider.name}`" :title="`编辑服务 ${provider.name}`" @click="edit(provider.provider_id)"><Pencil :size="16" /></button>
        <button type="button" :disabled="busy" :aria-label="`${provider.is_enabled === false ? '启用' : '停用'}服务 ${provider.name}`" @click="toggleEnabled(provider)">{{ provider.is_enabled === false ? '启用服务' : '停用服务' }}</button>
        <button type="button" :disabled="busy" @click="pendingDelete = provider.provider_id">删除服务</button>
      </div>
    </div>
    <div v-if="pendingDelete" class="settings-confirm" role="group" aria-label="删除模型服务确认">
      <p>删除服务 {{ pendingDelete }}？使用此服务的会话将无法继续调用它。</p>
      <button type="button" :disabled="busy" @click="pendingDelete = null">取消</button>
      <button type="button" :disabled="busy" @click="remove">确认删除服务</button>
    </div>
    <p v-if="error" role="alert">{{ error }}</p><p v-if="feedback" role="status">{{ feedback }}</p>
    <p v-if="busy" role="status">正在处理…</p>
    <details class="settings-resource-details" :open="editorOpen" @toggle="editorOpen = ($event.target as HTMLDetailsElement).open"><summary>{{ editing ? '编辑模型服务' : '添加模型服务' }}</summary>
      <form class="settings-form" @submit.prevent="save">
        <fieldset :disabled="busy">
          <label>服务名称<input v-model="name" required /></label>
          <label>服务标识<input v-model="providerId" required :readonly="!!editing" placeholder="例如 deepseek" /></label>
          <label>接口类型<select v-model="type"><option value="openai">OpenAI 兼容</option><option value="openai_responses">OpenAI Responses</option><option value="google">Gemini</option><option value="anthropic">Anthropic</option></select></label>
          <label>服务地址<input v-model="baseUrl" type="url" placeholder="留空使用官方默认地址" /></label>
          <template v-if="editing">
            <label>凭据变更<select v-model="credentialMode"><option value="keep">保留现有凭据{{ editing.has_api_key ? '（已配置）' : '（未配置）' }}</option><option value="key">更换当前运行密钥</option><option value="reference">更换密钥引用</option><option value="clear">清除凭据</option></select></label>
            <label v-if="credentialMode === 'key'">新的服务密钥<input v-model="apiKey" type="password" autocomplete="off" required /></label>
            <label v-if="credentialMode === 'reference'">密钥引用<input v-model="secretRef" placeholder="env:PROVIDER_API_KEY" required /></label>
            <div v-for="(entry, index) in modelEntries" :key="index" class="provider-model-entry">
              <div class="provider-model-heading"><h3>模型 {{ index + 1 }}</h3><button type="button" class="provider-icon-button" :aria-label="`移除模型 ${index + 1}`" :title="`移除模型 ${index + 1}`" @click="modelEntries.splice(index, 1)"><X :size="16" /></button></div>
              <label>模型 {{ index + 1 }} ID<input v-model="entry.config.model_id" required /></label>
              <div class="provider-model-capabilities"><label v-for="(label, value) in capabilityLabels" :key="value" class="settings-checkbox"><input v-model="entry.config.capabilities" type="checkbox" :value="value" :aria-label="`模型 ${index + 1} ${label}`" />{{ label }}</label></div>
            </div>
            <button type="button" @click="modelEntries.push({ key: '', config: { model_id: '', capabilities: ['chat'] } })"><Plus :size="16" />添加模型</button>
          </template>
          <template v-else>
            <label>服务密钥<input v-model="apiKey" type="password" autocomplete="off" /></label>
            <label>模型 ID<textarea v-model="modelIds" rows="3" placeholder="每行一个；也可用逗号分隔，可留空" /></label>
            <p class="settings-help">为以上模型声明服务实际支持的能力：</p>
            <label v-for="(label, value) in capabilityLabels" :key="value" class="settings-checkbox"><input v-model="capabilities" type="checkbox" :value="value" />{{ label }}</label>
          </template>
          <label class="settings-checkbox"><input v-model="discover" type="checkbox" />尝试从服务发现模型（可选）</label>
          <div class="settings-inline-actions"><button class="button-primary" type="submit"><Save v-if="editing" :size="16" />{{ editing ? '保存服务' : '添加服务' }}</button><button v-if="editing" type="button" @click="reset(); editorOpen = false">取消编辑</button></div>
        </fieldset>
      </form>
    </details>
  </section>
</template>

<style scoped>
.provider-icon-button { display: inline-flex; align-items: center; justify-content: center; width: 34px; height: 34px; padding: 0; }
.provider-model-entry { display: grid; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--color-border); }
.provider-model-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.provider-model-heading h3 { margin: 0; font-size: 14px; }
.provider-model-capabilities { display: flex; flex-wrap: wrap; gap: 10px 16px; }
.settings-inline-actions .button-primary, fieldset > button { display: inline-flex; align-items: center; justify-content: center; gap: 6px; }
</style>
