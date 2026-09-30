<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { testProvider, type ProviderInfo, type ProviderModelConfig, type ProviderTestResult } from '../../api/providers'

const props = defineProps<{ provider: ProviderInfo; models: ProviderModelConfig[]; disabled: boolean }>()
const emit = defineEmits<{ busy: [value: boolean]; close: [] }>()
const modelId = ref(props.models[0]?.model_id || '')
const busy = ref(false)
const error = ref('')
const result = ref<ProviderTestResult | null>(null)
let activeRequest: AbortController | null = null
const diagnostics: Record<string, string> = {
  ProviderAuthorizationError: '上游服务拒绝了当前凭据，请检查服务密钥和访问权限。',
  ProviderRequestTimeoutError: '模型请求超时，请检查服务地址或稍后重试。',
  ProviderRateLimitError: '上游服务限流或额度不足，请检查额度或稍后重试。',
  ProviderNotFoundError: '模型或上游资源不存在，请检查模型 ID 和服务地址。',
  ProviderUnavailableError: '无法连接上游服务，请检查地址和网络或稍后重试。',
  ProviderRequestError: '上游拒绝了模型请求，请检查模型权限和接口类型。',
}
const diagnostic = computed(() => diagnostics[result.value?.error_type || ''] || result.value?.error_message || '测试失败，请检查已保存的配置。')

function clearResult() { result.value = null; error.value = '' }
function cancelRequest() {
  activeRequest?.abort(); activeRequest = null; busy.value = false; emit('busy', false)
}
watch(() => props.provider, () => { cancelRequest(); clearResult() })
watch(modelId, clearResult)
onUnmounted(cancelRequest)

async function runTest() {
  if (busy.value || props.disabled || props.provider.is_enabled === false || !modelId.value.trim()) return
  clearResult(); busy.value = true; emit('busy', true)
  const controller = new AbortController()
  activeRequest = controller
  const timer = window.setTimeout(() => controller.abort(), 35_000)
  try {
    const response = await testProvider(props.provider.provider_id, modelId.value.trim(), controller.signal)
    if (activeRequest === controller) result.value = response
  } catch (cause) {
    if (activeRequest === controller) error.value = controller.signal.aborted
      ? '等待测试结果超时，请稍后重试。'
      : cause instanceof Error ? cause.message : '连接测试失败'
  } finally {
    window.clearTimeout(timer)
    if (activeRequest === controller) { activeRequest = null; busy.value = false; emit('busy', false) }
  }
}
</script>

<template>
  <section class="provider-connection-test" aria-label="服务连接测试">
    <h3>测试连接 · {{ provider.name }}</h3>
    <p class="settings-help">使用已保存的配置发送一条简短模型请求，可能产生调用费用。测试最长等待 30 秒，耗时包含模型生成时间。</p>
    <form class="settings-form" @submit.prevent="runTest">
      <fieldset :disabled="disabled">
      <label>测试模型<input v-model="modelId" list="provider-test-models" required maxlength="256" :disabled="disabled" placeholder="选择或输入模型 ID，无需预先声明" /></label>
      <datalist id="provider-test-models"><option v-for="model in models" :key="model.model_id" :value="model.model_id" /></datalist>
      <div class="settings-inline-actions">
        <button class="button-primary" type="submit" :disabled="disabled || provider.is_enabled === false || !modelId.trim()">{{ busy ? '正在测试…' : '开始测试' }}</button>
        <button type="button" :disabled="disabled" @click="emit('close')">关闭测试</button>
      </div>
      </fieldset>
    </form>
    <p v-if="provider.is_enabled === false" role="status">服务已停用，请先启用后再测试。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <div v-if="result" :role="result.success ? 'status' : 'alert'" aria-label="连接测试结果">
      <p>{{ result.success ? '连接测试成功' : '连接测试失败' }} · {{ result.elapsed_ms.toFixed(0) }} ms（含模型生成）</p>
      <p>请求模型：{{ result.model_id }}</p>
      <p v-if="result.success">响应模型：{{ result.response_model_id || '未报告' }}</p>
      <p v-else>{{ diagnostic }}</p>
    </div>
  </section>
</template>

<style scoped>
.provider-connection-test { padding: 16px 0; border-bottom: 1px solid var(--color-border); overflow-wrap: anywhere; }
.provider-connection-test h3 { margin: 0 0 10px; font-size: 14px; }
.provider-connection-test button { padding: 7px 16px; border-radius: 20px; }
</style>
