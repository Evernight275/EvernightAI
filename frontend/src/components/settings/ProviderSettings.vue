<script setup lang="ts">
import { ref } from 'vue'
import { createProvider, deleteProvider, type ProviderType, type ProviderModelCapability } from '../../api/providers'
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
async function save() {
  if (busy.value) return
  busy.value = true; error.value = ''; feedback.value = ''
  try {
    if (props.catalog.providers.some(item => item.provider_id === providerId.value.trim())) throw new Error('此服务标识已存在，请使用新的标识')
    const ids = [...new Set(modelIds.value.split(/[,\n]/).map(id => id.trim()).filter(Boolean))]
    await createProvider({ provider_id: providerId.value.trim(), name: name.value.trim(), type: type.value,
      base_url: baseUrl.value.trim() || null, api_key: apiKey.value || null, discover_models: discover.value,
      model: Object.fromEntries(ids.map(model_id => [model_id, { model_id, capabilities: [...capabilities.value] }])),
    })
    apiKey.value = ''; providerId.value = ''; name.value = ''; baseUrl.value = ''; modelIds.value = ''
    feedback.value = '模型服务已添加'; emit('changed')
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '添加失败' }
  finally { busy.value = false }
}
async function remove() {
  if (!pendingDelete.value) return
  busy.value = true; error.value = ''
  try { await deleteProvider(pendingDelete.value); pendingDelete.value = null; feedback.value = '模型服务已删除'; emit('changed') }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '删除失败' }
  finally { busy.value = false }
}
</script>

<template>
  <section class="settings-manager" aria-label="模型服务管理">
    <div v-for="provider in catalog.providers" :key="provider.provider_id" class="settings-row">
      <div><h3>{{ provider.name }}</h3><p>{{ provider.type }} · {{ provider.is_enabled === false ? '已停用' : '已启用' }}</p>
        <p>{{ catalog.modelGroups.find(group => group.provider.provider_id === provider.provider_id)?.models.map(model => model.model_id).join('、') || '未声明模型' }}</p></div>
      <button type="button" :disabled="busy" @click="pendingDelete = provider.provider_id">删除服务</button>
    </div>
    <div v-if="pendingDelete" class="settings-confirm" role="group" aria-label="删除模型服务确认">
      <p>删除服务 {{ pendingDelete }}？使用此服务的会话将无法继续调用它。</p>
      <button type="button" :disabled="busy" @click="pendingDelete = null">取消</button>
      <button type="button" :disabled="busy" @click="remove">确认删除服务</button>
    </div>
    <details class="settings-resource-details"><summary>添加模型服务</summary>
      <form class="settings-form" @submit.prevent="save">
        <fieldset :disabled="busy">
          <label>服务名称<input v-model="name" required /></label>
          <label>服务标识<input v-model="providerId" required placeholder="例如 deepseek" /></label>
          <label>接口类型<select v-model="type"><option value="openai">OpenAI 兼容</option><option value="openai_responses">OpenAI Responses</option><option value="google">Gemini</option><option value="anthropic">Anthropic</option></select></label>
          <label>服务地址<input v-model="baseUrl" type="url" placeholder="留空使用官方默认地址" /></label>
          <label>服务密钥<input v-model="apiKey" type="password" autocomplete="off" /></label>
          <label>模型 ID<textarea v-model="modelIds" rows="3" placeholder="每行一个；也可用逗号分隔，可留空" /></label>
          <p class="settings-help">为以上模型声明服务实际支持的能力：</p>
          <label v-for="(label, value) in capabilityLabels" :key="value" class="settings-checkbox"><input v-model="capabilities" type="checkbox" :value="value" />{{ label }}</label>
          <label class="settings-checkbox"><input v-model="discover" type="checkbox" />尝试从服务发现模型（可选）</label>
          <button class="button-primary" type="submit">{{ busy ? '正在添加…' : '添加服务' }}</button>
        </fieldset>
      </form>
    </details>
    <p v-if="error" role="alert">{{ error }}</p><p v-if="feedback" role="status">{{ feedback }}</p>
  </section>
</template>
