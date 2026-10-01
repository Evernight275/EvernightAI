<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Download, ExternalLink, ImagePlus, LoaderCircle, Square } from '@lucide/vue'
import { generateImages, type GeneratedImage, type ImageGenerationRecord, type ImageGenerationRequest, type ImageGenerationResponse, type ProviderInfo } from '../../api'
import { downloadImage, imageSource } from '../../domain/images'

const props = defineProps<{ providers: ProviderInfo[]; record?: ImageGenerationRecord | null; clearedRecordId?: string }>()
const emit = defineEmits<{ generated: [response: ImageGenerationResponse]; busy: [value: boolean] }>()
const providers = computed(() => props.providers.filter(p => p.type === 'openai' && p.is_enabled !== false))
const providerId = ref('')
const modelId = ref('')
const prompt = ref('')
const count = ref(1)
const size = ref('')
const quality = ref('')
const outputFormat = ref<ImageGenerationRequest['output_format'] | ''>('')
const background = ref<ImageGenerationRequest['background'] | ''>('')
const resultFormat = ref<ImageGenerationRequest['result_format'] | ''>('')
const timeout = ref(180)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const result = ref<ImageGenerationResponse | null>(null)
const submitted = ref<ImageGenerationRequest | null>(null)
const failedImages = ref(new Set<number>())
const downloading = ref<number | null>(null)
let controller: AbortController | null = null
let downloadController: AbortController | null = null
let generation = 0
let downloadVersion = 0
const models = computed(() => Object.values(providers.value.find(p => p.provider_id === providerId.value)?.model || {})
  .filter(m => !m.capabilities?.length || m.capabilities.includes('image_generation')))
watch(providers, value => {
  if (!value.some(p => p.provider_id === providerId.value)) providerId.value = value[0]?.provider_id || ''
}, { immediate: true })
watch(providerId, () => { modelId.value = models.value[0]?.model_id || '' }, { immediate: true, flush: 'sync' })
watch(busy, value => emit('busy', value))
watch(() => props.record, record => {
  if (!record || busy.value) return
  generation++; downloadVersion++; downloadController?.abort(); downloading.value = null
  const request = record.request
  providerId.value = providers.value.some(p => p.provider_id === record.provider_id) ? record.provider_id : ''
  modelId.value = request.model_id; prompt.value = request.prompt; count.value = request.count ?? 1
  size.value = request.size ?? ''; quality.value = request.quality ?? ''; outputFormat.value = request.output_format ?? ''
  background.value = request.background ?? ''; resultFormat.value = request.result_format ?? ''; timeout.value = request.timeout_seconds ?? 180
  result.value = record.response; submitted.value = request; failedImages.value = new Set()
  error.value = ''; notice.value = ''
})
watch(() => props.clearedRecordId, id => {
  if (id && result.value?.record_id === id) { result.value = null; submitted.value = null; generation++; downloadVersion++; downloadController?.abort(); downloading.value = null }
})

async function generate(): Promise<void> {
  if (busy.value || !providerId.value || !modelId.value.trim() || !prompt.value.trim()) return
  const request: ImageGenerationRequest = {
    model_id: modelId.value.trim(), prompt: prompt.value, count: count.value, timeout_seconds: timeout.value,
    ...(size.value ? { size: size.value } : {}), ...(quality.value ? { quality: quality.value } : {}),
    ...(outputFormat.value ? { output_format: outputFormat.value } : {}),
    ...(background.value ? { background: background.value } : {}),
    ...(resultFormat.value ? { result_format: resultFormat.value } : {}),
  }
  const current = ++generation
  controller = new AbortController()
  busy.value = true; error.value = ''; notice.value = ''
  try {
    const response = await generateImages(providerId.value, request, controller.signal)
    if (current !== generation) return
    downloadVersion++; downloadController?.abort(); downloading.value = null
    result.value = response; submitted.value = request; failedImages.value = new Set()
    emit('generated', response)
  } catch (cause) {
    if (current === generation) error.value = cause instanceof Error ? cause.message : '生成失败，请重试'
  } finally {
    if (current === generation) { busy.value = false; controller = null }
  }
}
function cancel(): void {
  generation++; controller?.abort(); controller = null; busy.value = false
  notice.value = '已取消等待，服务商可能仍在生成并计费。'
}
async function download(image: GeneratedImage, index: number): Promise<void> {
  if (downloading.value !== null) return
  downloading.value = index; error.value = ''
  const current = ++downloadVersion
  downloadController = new AbortController()
  try { await downloadImage(image, index, downloadController.signal) }
  catch (cause) { if (current === downloadVersion) error.value = cause instanceof Error ? cause.message : '下载失败，可打开原图保存' }
  finally { if (current === downloadVersion) { downloading.value = null; downloadController = null } }
}
onBeforeUnmount(() => { generation++; downloadVersion++; controller?.abort(); downloadController?.abort() })
</script>

<template>
  <div class="image-workspace">
    <form class="image-controls" @submit.prevent="generate">
      <h2>生成参数</h2>
      <fieldset :disabled="busy">
        <label>服务商<select v-model="providerId" required aria-label="服务商"><option value="" disabled>选择服务商</option><option v-for="p in providers" :key="p.provider_id" :value="p.provider_id">{{ p.name }}</option></select></label>
        <label>模型<input v-model="modelId" list="image-models" required maxlength="256" aria-label="模型" autocomplete="off" /><datalist id="image-models"><option v-for="m in models" :key="m.model_id" :value="m.model_id" /></datalist></label>
        <label>提示词<textarea v-model="prompt" required maxlength="32000" rows="7" aria-label="提示词" /></label>
        <div class="image-options">
          <label>数量<input v-model.number="count" type="number" min="1" max="10" step="1" required aria-label="数量" /></label>
          <label>尺寸<input v-model="size" list="image-sizes" maxlength="64" placeholder="模型默认" aria-label="尺寸" /><datalist id="image-sizes"><option value="1024x1024" /><option value="1536x1024" /><option value="1024x1536" /><option value="1792x1024" /><option value="1024x1792" /></datalist></label>
          <label>质量<input v-model="quality" list="image-quality" maxlength="64" placeholder="模型默认" aria-label="质量" /><datalist id="image-quality"><option value="low" /><option value="medium" /><option value="high" /><option value="standard" /><option value="hd" /></datalist></label>
          <label>文件格式<select v-model="outputFormat" aria-label="文件格式"><option value="">模型默认</option><option value="png">PNG</option><option value="jpeg">JPEG</option><option value="webp">WebP</option></select></label>
        </div>
        <details><summary>更多参数</summary><div class="image-options">
          <label>背景<select v-model="background" aria-label="背景"><option value="">模型默认</option><option value="auto">自动</option><option value="transparent">透明</option><option value="opaque">不透明</option></select></label>
          <label>返回方式<select v-model="resultFormat" aria-label="返回方式"><option value="">模型默认</option><option value="base64">Base64</option><option value="url">URL</option></select></label>
          <label>超时（秒）<input v-model.number="timeout" type="number" min="1" max="600" required aria-label="超时（秒）" /></label>
        </div></details>
      </fieldset>
      <p v-if="!providers.length" class="image-muted">暂无可用的 OpenAI-compatible 服务商</p>
      <div class="image-actions"><button class="button-primary" :disabled="busy || !providerId || !modelId.trim() || !prompt.trim()" type="submit"><LoaderCircle v-if="busy" :size="17" class="image-spinner" /><ImagePlus v-else :size="17" />{{ busy ? '正在生成' : '生成图片' }}</button><button v-if="busy" type="button" @click="cancel"><Square :size="16" />取消等待</button></div>
      <p v-if="error" role="alert" class="image-error">{{ error }}</p>
      <p v-if="notice" role="status" class="image-muted">{{ notice }}</p>
    </form>
    <section class="image-results" tabindex="-1" aria-label="生成结果" :aria-busy="busy">
      <header><h2>生成结果</h2><span v-if="result" class="image-muted">{{ result.images.length }} 张 · {{ result.model_id }}</span></header>
      <p v-if="!result" class="image-empty" role="status">{{ busy ? '正在生成…' : '暂无图片' }}</p>
      <template v-else>
        <p v-if="result.persistence_warning" class="image-error" role="status">{{ result.persistence_warning === 'save_failed' ? '图片已生成，但保存失败。请先下载图片，避免重新生成。' : result.persistence_warning === 'record_deleted' ? '记录已在其他窗口删除，当前图片仍可下载。' : '部分图片未能归档，远程链接可能过期。请先下载图片。' }}</p>
        <p v-else-if="result.record_id" class="image-muted">已保存</p>
        <div class="image-grid"><figure v-for="(image, index) in result.images" :key="index">
          <div class="image-preview"><img v-if="imageSource(image) && !failedImages.has(index)" :src="imageSource(image)" :alt="`生成图片 ${index + 1}`" referrerpolicy="no-referrer" @error="failedImages.add(index)" /><span v-else>图片无法加载</span></div>
          <figcaption><span>图片 {{ index + 1 }}</span><div class="image-actions"><button class="icon-button" type="button" :disabled="downloading !== null || !imageSource(image)" :aria-label="`下载图片 ${index + 1}`" title="下载图片" @click="download(image, index)"><Download :size="18" /></button><a v-if="imageSource(image) && !imageSource(image).startsWith('data:')" class="icon-button" :href="imageSource(image)" target="_blank" rel="noopener noreferrer" :aria-label="`打开原图 ${index + 1}`" title="打开原图"><ExternalLink :size="18" /></a></div></figcaption>
          <details v-if="image.revised_prompt"><summary>调整后的提示词</summary><p>{{ image.revised_prompt }}</p></details>
        </figure></div>
        <details class="image-submitted"><summary>本次生成参数</summary><p>{{ submitted?.prompt }}</p><p class="image-muted">{{ submitted?.size || '默认尺寸' }} · {{ submitted?.quality || '默认质量' }} · {{ submitted?.output_format || '默认格式' }}</p></details>
        <p v-if="result.usage" class="image-muted">输入 {{ result.usage.input_tokens ?? '未知' }} · 输出 {{ result.usage.output_tokens ?? '未知' }} · 总计 {{ result.usage.total_tokens ?? '未知' }} tokens</p>
      </template>
    </section>
  </div>
</template>
