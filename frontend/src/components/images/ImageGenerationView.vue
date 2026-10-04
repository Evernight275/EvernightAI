<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import {
  Download,
  ExternalLink,
  ImagePlus,
  Image,
  LoaderCircle,
  SlidersHorizontal,
  Square,
  ChevronLeft,
  ChevronRight,
  X,
} from '@lucide/vue';
import {
  type GeneratedImage,
  type ImageEditInput,
  type ImageEditRequest,
  type ImageGenerationRecord,
  type ImageGenerationRequest,
  type ImageGenerationResponse,
  type ProviderInfo,
} from '../../api';
import {
  getImageRecord,
  submitImageTask,
  type ImageMaskInput,
  type ImageTask,
  type ImageTaskSubmission,
} from '../../api/images';
import { imageTaskLabels, waitForImageTask } from '../../runtime/imageTasks';
import ImageMaskEditor from './ImageMaskEditor.vue';
import {
  downloadImage,
  imageSource,
  imageEditInputs,
  imageErrorMessage,
  imageInputSize,
  MAX_IMAGE_INPUT_COUNT,
  readImageUpload,
  validateImageUploads,
} from '../../domain/images';

const props = defineProps<{
  providers: ProviderInfo[];
  record?: ImageGenerationRecord | null;
  clearedRecordId?: string;
  sessionId?: string;
  editImage?: { id: string; image: GeneratedImage; providerId: string; modelId: string } | null;
}>();
const emit = defineEmits<{
  generated: [response: ImageGenerationResponse];
  busy: [value: boolean];
  queued: [task: ImageTask];
}>();
const providers = computed(() =>
  props.providers.filter((p) => p.type === 'openai' && p.is_enabled !== false),
);
const providerId = ref('');
const modelId = ref('');
const prompt = ref('');
const mode = ref<'generate' | 'edit'>('generate');
type ReferenceImage = { id: number; image: ImageEditInput; name: string; size: number };
const references = ref<ReferenceImage[]>([]);
const maskEnabled = ref(false);
const maskBusy = ref(false);
const initialMask = ref<ImageMaskInput | null>(null);
const preparedMask = ref<{ image: ImageEditInput; mask: ImageMaskInput } | null>(null);
const activeTask = ref<ImageTask | null>(null);
let pendingSubmission: ImageTaskSubmission | null = null;
let imageSequence = 0;
const uploadInput = ref<HTMLInputElement | null>(null);
const uploading = ref(false);
let uploadController: AbortController | null = null;
let uploadVersion = 0;
const count = ref(1);
const size = ref('');
const quality = ref('');
const outputFormat = ref<ImageGenerationRequest['output_format'] | ''>('');
const background = ref<ImageGenerationRequest['background'] | ''>('');
const resultFormat = ref<ImageGenerationRequest['result_format'] | ''>('');
const timeout = ref(180);
const busy = ref(false);
const error = ref('');
const notice = ref('');
const result = ref<ImageGenerationResponse | null>(null);
const submitted = ref<ImageGenerationRequest | null>(null);
const failedImages = ref(new Set<number>());
const downloading = ref<number | null>(null);
const downloadNames = ref<string[]>([]);
let controller: AbortController | null = null;
let downloadController: AbortController | null = null;
let generation = 0;
let downloadVersion = 0;
const models = computed(() =>
  Object.values(
    providers.value.find((p) => p.provider_id === providerId.value)?.model || {},
  ).filter((m) => !m.capabilities?.length || m.capabilities.includes('image_generation')),
);
watch(
  providers,
  (value) => {
    if (!value.some((p) => p.provider_id === providerId.value))
      providerId.value = value[0]?.provider_id || '';
  },
  { immediate: true },
);
watch(
  providerId,
  () => {
    modelId.value = models.value[0]?.model_id || '';
  },
  { immediate: true, flush: 'sync' },
);
watch([busy, uploading, maskBusy], ([generating, reading, masking]) =>
  emit('busy', generating || reading || masking),
);
watch(
  () => references.value[0]?.id,
  () => {
    preparedMask.value = null;
    initialMask.value = null;
    maskEnabled.value = false;
  },
  { flush: 'sync' },
);
watch(
  () => props.editImage,
  (value) => {
    if (value) continueEditing(value.image, value.providerId, value.modelId);
  },
  { immediate: true },
);
watch(
  mode,
  () => {
    clearReferences();
    error.value = '';
    notice.value = '';
  },
  { flush: 'sync' },
);
watch(
  result,
  (value) => {
    downloadNames.value = value?.images.map((_, index) => `evernight-image-${index + 1}`) || [];
  },
  { flush: 'sync' },
);
watch(
  () => props.record,
  (record) => {
    if (!record || busy.value) return;
    generation++;
    downloadVersion++;
    downloadController?.abort();
    downloading.value = null;
    const request = record.request;
    clearReferences();
    const images = imageEditInputs(request);
    mode.value = images.length ? 'edit' : 'generate';
    references.value = images.map((image, index) => ({
      id: ++imageSequence,
      image,
      name: `历史参考图 ${index + 1}`,
      size: imageInputSize(image),
    }));
    initialMask.value = 'mask' in request ? request.mask || null : null;
    maskEnabled.value = !!initialMask.value;
    providerId.value = providers.value.some((p) => p.provider_id === record.provider_id)
      ? record.provider_id
      : '';
    modelId.value = request.model_id;
    prompt.value = request.prompt;
    count.value = request.count ?? 1;
    size.value = request.size ?? '';
    quality.value = request.quality ?? '';
    outputFormat.value = request.output_format ?? '';
    background.value = request.background ?? '';
    resultFormat.value = request.result_format ?? '';
    timeout.value = request.timeout_seconds ?? 180;
    result.value = record.response;
    submitted.value = request;
    failedImages.value = new Set();
    error.value = '';
    notice.value = '';
  },
);
watch(
  () => props.clearedRecordId,
  (id) => {
    if (id && result.value?.record_id === id) {
      if (submitted.value && imageEditInputs(submitted.value).length) clearReferences();
      result.value = null;
      submitted.value = null;
      generation++;
      downloadVersion++;
      downloadController?.abort();
      downloading.value = null;
    }
  },
);

async function generate(): Promise<void> {
  if (
    busy.value ||
    uploading.value ||
    maskBusy.value ||
    !providerId.value ||
    !modelId.value.trim() ||
    !prompt.value.trim() ||
    (mode.value === 'edit' && !references.value.length)
  )
    return;
  const request: ImageGenerationRequest = {
    model_id: modelId.value.trim(),
    prompt: prompt.value,
    count: count.value,
    timeout_seconds: timeout.value,
    ...(size.value ? { size: size.value } : {}),
    ...(quality.value ? { quality: quality.value } : {}),
    ...(outputFormat.value ? { output_format: outputFormat.value } : {}),
    ...(background.value ? { background: background.value } : {}),
    ...(resultFormat.value ? { result_format: resultFormat.value } : {}),
  };
  if (mode.value === 'edit' && maskEnabled.value && !preparedMask.value) {
    error.value = '请先涂抹需要修改的区域，或关闭局部修改。';
    return;
  }
  const editRequest: ImageEditRequest | null =
    mode.value === 'edit' && references.value.length
      ? { ...request, images: references.value.map((item) => ({ ...item.image })) }
      : null;
  if (editRequest && maskEnabled.value && preparedMask.value) {
    editRequest.images[0] = preparedMask.value.image;
    editRequest.mask = preparedMask.value.mask;
    const total = [...editRequest.images, editRequest.mask].reduce(
      (sum, input) => sum + imageInputSize(input),
      0,
    );
    if (total > 50 * 1024 * 1024) {
      error.value = '参考图与遮罩总大小不能超过 50 MiB';
      return;
    }
  }
  const current = ++generation;
  controller = new AbortController();
  busy.value = true;
  error.value = '';
  notice.value = '';
  activeTask.value = null;
  try {
    const next = {
      provider_id: providerId.value,
      request: editRequest || request,
      ...(props.sessionId ? { session_id: props.sessionId } : {}),
    };
    if (
      !pendingSubmission ||
      JSON.stringify({ ...pendingSubmission, task_id: undefined }) !== JSON.stringify(next)
    ) {
      pendingSubmission = { ...next, task_id: crypto.randomUUID().replaceAll('-', '') };
    }
    const task = await submitImageTask(pendingSubmission, controller.signal);
    if (current !== generation) return;
    activeTask.value = task;
    emit('queued', task);
    pendingSubmission = null;
    const finished = await waitForImageTask(task, controller.signal, (value) => {
      if (current === generation) activeTask.value = value;
    });
    if (finished.status !== 'succeeded' || !finished.record_id)
      throw new Error(finished.error_message || '图片任务未完成，请检查任务列表。');
    const record = await getImageRecord(finished.record_id, controller.signal);
    const response = record.response;
    if (current !== generation) return;
    downloadVersion++;
    downloadController?.abort();
    downloading.value = null;
    result.value = response;
    submitted.value = editRequest || request;
    failedImages.value = new Set();
    emit('generated', response);
  } catch (cause) {
    if (current === generation) {
      error.value = imageErrorMessage(cause);
      if (activeTask.value && ['queued', 'running'].includes(activeTask.value.status))
        notice.value = '任务仍在后台执行，请在图片任务中查看进度。';
    }
  } finally {
    if (current === generation) {
      busy.value = false;
      controller = null;
    }
  }
}
function clearReferences(): void {
  uploadVersion++;
  uploadController?.abort();
  uploadController = null;
  uploading.value = false;
  references.value = [];
  maskEnabled.value = false;
  preparedMask.value = null;
  initialMask.value = null;
  if (uploadInput.value) uploadInput.value.value = '';
}
async function upload(event: Event): Promise<void> {
  const files = Array.from((event.target as HTMLInputElement).files || []);
  if (uploadInput.value) uploadInput.value.value = '';
  if (!files.length || busy.value || uploading.value) return;
  error.value = '';
  try {
    validateImageUploads(files, references.value);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '无法读取图片';
    return;
  }
  const current = ++uploadVersion;
  const readController = new AbortController();
  uploadController = readController;
  uploading.value = true;
  try {
    const added: ReferenceImage[] = [];
    for (const file of files) {
      const image = await readImageUpload(file, readController.signal);
      if (current !== uploadVersion) return;
      added.push({ id: ++imageSequence, image, name: file.name, size: file.size });
    }
    references.value = [...references.value, ...added];
  } catch (cause) {
    if (current === uploadVersion)
      error.value = cause instanceof Error ? cause.message : '无法读取图片';
  } finally {
    if (current === uploadVersion) {
      uploading.value = false;
      uploadController = null;
    }
  }
}
function removeReference(index: number): void {
  if (busy.value || uploading.value) return;
  references.value.splice(index, 1);
  error.value = '';
}
function moveReference(index: number, direction: -1 | 1): void {
  const target = index + direction;
  if (busy.value || uploading.value || target < 0 || target >= references.value.length) return;
  const items = [...references.value];
  const [item] = items.splice(index, 1);
  if (!item) return;
  items.splice(target, 0, item);
  references.value = items;
}
function cancel(): void {
  generation++;
  controller?.abort();
  controller = null;
  busy.value = false;
  notice.value = '已取消等待，任务会继续在后台生成，可在图片任务中查看结果。';
}
function continueEditing(
  image: GeneratedImage,
  provider = providerId.value,
  model = modelId.value,
): void {
  if (busy.value || !image.base64_data || !image.mime_type) return;
  clearReferences();
  mode.value = 'edit';
  const input = { base64_data: image.base64_data, mime_type: image.mime_type };
  references.value = [
    { id: ++imageSequence, image: input, name: '生成图片', size: imageInputSize(input) },
  ];
  providerId.value = providers.value.some((p) => p.provider_id === provider)
    ? provider
    : providers.value[0]?.provider_id || '';
  modelId.value = model;
  prompt.value = '';
  error.value = '';
  notice.value = '已将生成图片设为参考图，描述修改要求后开始改图。';
}
async function download(image: GeneratedImage, index: number): Promise<void> {
  if (downloading.value !== null) return;
  downloading.value = index;
  error.value = '';
  const current = ++downloadVersion;
  downloadController = new AbortController();
  try {
    await downloadImage(image, index, downloadController.signal, downloadNames.value[index]);
  } catch (cause) {
    if (current === downloadVersion)
      error.value = cause instanceof Error ? cause.message : '下载失败，可打开原图保存';
  } finally {
    if (current === downloadVersion) {
      downloading.value = null;
      downloadController = null;
    }
  }
}
onBeforeUnmount(() => {
  generation++;
  downloadVersion++;
  controller?.abort();
  downloadController?.abort();
  clearReferences();
});
</script>

<template>
  <div class="image-workspace">
    <form class="image-controls" @submit.prevent="generate">
      <header class="image-controls-header">
        <SlidersHorizontal :size="17" aria-hidden="true" />
        <h2>生成参数</h2>
      </header>
      <fieldset :disabled="busy">
        <div class="image-mode" role="group" aria-label="创作方式">
          <button type="button" :aria-pressed="mode === 'generate'" @click="mode = 'generate'">
            文字生图
          </button>
          <button type="button" :aria-pressed="mode === 'edit'" @click="mode = 'edit'">
            上传改图
          </button>
        </div>
        <label
          >服务商<select v-model="providerId" required aria-label="服务商">
            <option value="" disabled>选择服务商</option>
            <option v-for="p in providers" :key="p.provider_id" :value="p.provider_id">
              {{ p.name }}
            </option>
          </select></label
        >
        <label
          >模型<input
            v-model="modelId"
            list="image-models"
            required
            maxlength="256"
            aria-label="模型"
            autocomplete="off"
            placeholder="选择或输入模型名称" /><datalist id="image-models">
            <option v-for="m in models" :key="m.model_id" :value="m.model_id" /></datalist
        ></label>
        <div v-if="mode === 'edit'" class="image-upload">
          <div class="image-upload-field">
            <span
              >参考图
              <span class="image-muted"
                >{{ references.length }} / {{ MAX_IMAGE_INPUT_COUNT }}</span
              ></span
            ><button
              type="button"
              class="image-upload-picker"
              :disabled="uploading || references.length >= MAX_IMAGE_INPUT_COUNT"
              @click="uploadInput?.click()"
            >
              <ImagePlus :size="16" />{{ references.length ? '继续添加图片' : '选择图片' }}
            </button>
          </div>
          <input
            ref="uploadInput"
            type="file"
            accept="image/png,image/jpeg,image/webp"
            multiple
            :disabled="uploading"
            aria-label="上传参考图"
            hidden
            @change="upload"
          />
          <p class="image-muted">
            支持 PNG、JPEG、WebP，单张最大 20 MiB，总计 50 MiB。请选择支持多图改图的模型。
          </p>
          <label v-if="references.length" class="image-mask-toggle"
            ><input
              v-model="maskEnabled"
              type="checkbox"
              :disabled="busy || uploading"
            />局部涂抹修改图 1</label
          >
          <ImageMaskEditor
            v-if="maskEnabled && references[0]"
            :key="references[0].id"
            :image="references[0].image"
            :initial-mask="initialMask"
            :disabled="busy || uploading"
            @change="preparedMask = $event"
            @busy="maskBusy = $event"
          />
          <p v-if="uploading" class="image-muted" role="status">正在读取图片…</p>
          <div v-if="references.length" class="image-reference-grid">
            <figure v-for="(item, index) in references" :key="item.id">
              <div class="image-original-preview">
                <img :src="imageSource(item.image)" :alt="`参考图 ${index + 1}`" />
              </div>
              <figcaption>
                <strong>图 {{ index + 1 }}</strong
                ><span :title="item.name">{{ item.name }}</span>
              </figcaption>
              <div class="image-actions">
                <button
                  class="icon-button"
                  type="button"
                  :aria-label="`前移参考图 ${index + 1}`"
                  title="前移"
                  :disabled="uploading || index === 0"
                  @click="moveReference(index, -1)"
                >
                  <ChevronLeft :size="16" />
                </button>
                <button
                  class="icon-button"
                  type="button"
                  :aria-label="`后移参考图 ${index + 1}`"
                  title="后移"
                  :disabled="uploading || index === references.length - 1"
                  @click="moveReference(index, 1)"
                >
                  <ChevronRight :size="16" />
                </button>
                <button
                  class="icon-button"
                  type="button"
                  :aria-label="`移除参考图 ${index + 1}`"
                  title="移除"
                  :disabled="uploading"
                  @click="removeReference(index)"
                >
                  <X :size="16" />
                </button>
              </div>
            </figure>
          </div>
          <p v-if="references.length" class="image-muted">
            可在修改要求中使用“图 1”“图 2”指定参考图。顺序与提交顺序一致。
          </p>
        </div>
        <label
          >{{ mode === 'edit' ? '修改要求' : '提示词'
          }}<textarea
            v-model="prompt"
            required
            maxlength="32000"
            rows="6"
            :aria-label="mode === 'edit' ? '修改要求' : '提示词'"
            :placeholder="
              mode === 'edit'
                ? '例如：保留图 1 的主体，使用图 2 的背景和图 3 的配色…'
                : '描述你想生成的画面、风格与细节…'
            "
          />
        </label>
        <div class="image-options">
          <label
            >数量<input
              v-model.number="count"
              type="number"
              min="1"
              max="10"
              step="1"
              required
              aria-label="数量"
          /></label>
          <label
            >尺寸<input
              v-model="size"
              list="image-sizes"
              maxlength="64"
              placeholder="模型默认"
              aria-label="尺寸" /><datalist id="image-sizes">
              <option value="1024x1024" />
              <option value="1536x1024" />
              <option value="1024x1536" />
              <option value="1792x1024" />
              <option value="1024x1792" /></datalist
          ></label>
          <label
            >质量<input
              v-model="quality"
              list="image-quality"
              maxlength="64"
              placeholder="模型默认"
              aria-label="质量" /><datalist id="image-quality">
              <option value="low" />
              <option value="medium" />
              <option value="high" />
              <option value="standard" />
              <option value="hd" /></datalist
          ></label>
          <label
            >文件格式<select v-model="outputFormat" aria-label="文件格式">
              <option value="">模型默认</option>
              <option value="png">PNG</option>
              <option value="jpeg">JPEG</option>
              <option value="webp">WebP</option>
            </select></label
          >
        </div>
        <details>
          <summary>更多参数</summary>
          <div class="image-options">
            <label
              >背景<select v-model="background" aria-label="背景">
                <option value="">模型默认</option>
                <option value="auto">自动</option>
                <option value="transparent">透明</option>
                <option value="opaque">不透明</option>
              </select></label
            >
            <label
              >返回方式<select v-model="resultFormat" aria-label="返回方式">
                <option value="">模型默认</option>
                <option value="base64">Base64</option>
                <option value="url">URL</option>
              </select></label
            >
            <label
              >超时（秒）<input
                v-model.number="timeout"
                type="number"
                min="1"
                max="600"
                required
                aria-label="超时（秒）"
            /></label>
          </div>
        </details>
      </fieldset>
      <p v-if="!providers.length" class="image-muted">暂无可用的 OpenAI-compatible 服务商</p>
      <div class="image-actions">
        <button
          class="button-primary"
          :disabled="
            busy ||
            uploading ||
            maskBusy ||
            !providerId ||
            !modelId.trim() ||
            !prompt.trim() ||
            (mode === 'edit' && !references.length)
          "
          type="submit"
        >
          <LoaderCircle v-if="busy" :size="17" class="image-spinner" /><ImagePlus
            v-else
            :size="17"
          />{{ busy ? '正在生成' : mode === 'edit' ? '开始改图' : '生成图片' }}</button
        ><button v-if="busy" type="button" @click="cancel"><Square :size="16" />取消等待</button>
      </div>
      <p v-if="error" role="alert" class="image-error">{{ error }}</p>
      <p v-if="notice" role="status" class="image-muted">{{ notice }}</p>
      <p v-if="activeTask" role="status" class="image-muted">
        {{ imageTaskLabels[activeTask.status] }} · 刷新页面后可在图片任务中继续查看。
      </p>
    </form>
    <section class="image-results" tabindex="-1" aria-label="生成结果" :aria-busy="busy">
      <header>
        <h2>生成结果</h2>
        <span v-if="result" class="image-muted"
          >{{ result.images.length }} 张 · {{ result.model_id }}</span
        >
      </header>
      <div v-if="!result" class="image-empty" role="status">
        <span class="image-empty-icon"
          ><LoaderCircle v-if="busy" :size="26" class="image-spinner" aria-hidden="true" /><Image
            v-else
            :size="26"
            aria-hidden="true"
        /></span>
        <h3>{{ busy ? '正在生成…' : '暂无图片' }}</h3>
        <p>
          {{
            busy
              ? '画面正在成形，请稍候'
              : mode === 'edit'
                ? '上传参考图并描述修改要求，开始创作'
                : '写下画面描述，开始创作你的第一张图片'
          }}
        </p>
      </div>
      <template v-else>
        <p v-if="result.persistence_warning" class="image-error" role="status">
          {{
            result.persistence_warning === 'save_failed'
              ? '图片已生成，但保存失败。请先下载图片，避免重新生成。'
              : result.persistence_warning === 'record_deleted'
                ? '记录已在其他窗口删除，当前图片仍可下载。'
                : '部分图片未能归档，远程链接可能过期。请先下载图片。'
          }}
        </p>
        <p v-else-if="result.record_id" class="image-muted">已保存</p>
        <div class="image-grid">
          <figure v-for="(image, index) in result.images" :key="index">
            <div class="image-preview">
              <img
                v-if="imageSource(image) && !failedImages.has(index)"
                :src="imageSource(image)"
                :alt="`生成图片 ${index + 1}`"
                referrerpolicy="no-referrer"
                @error="failedImages.add(index)"
              /><span v-else>图片无法加载</span>
            </div>
            <figcaption>
              <span>图片 {{ index + 1 }}</span>
              <div class="image-actions">
                <button
                  type="button"
                  :disabled="busy || !image.base64_data"
                  :aria-label="`继续修改图片 ${index + 1}`"
                  @click="continueEditing(image)"
                >
                  继续修改
                </button>
                <button
                  class="icon-button"
                  type="button"
                  :disabled="downloading !== null || !imageSource(image)"
                  :aria-label="`下载图片 ${index + 1}`"
                  title="下载图片"
                  @click="download(image, index)"
                >
                  <Download :size="18" /></button
                ><a
                  v-if="imageSource(image) && !imageSource(image).startsWith('data:')"
                  class="icon-button"
                  :href="imageSource(image)"
                  target="_blank"
                  rel="noopener noreferrer"
                  :aria-label="`打开原图 ${index + 1}`"
                  title="打开原图"
                  ><ExternalLink :size="18"
                /></a>
              </div>
            </figcaption>
            <label class="image-filename"
              >文件名<input
                v-model="downloadNames[index]"
                :aria-label="`图片 ${index + 1} 文件名`"
                :placeholder="`evernight-image-${index + 1}`"
                maxlength="80"
                autocomplete="off"
                :disabled="downloading !== null"
            /></label>
            <details v-if="image.revised_prompt">
              <summary>调整后的提示词</summary>
              <p>{{ image.revised_prompt }}</p>
            </details>
          </figure>
        </div>
        <p class="image-muted">可修改文件名后下载，扩展名按图片格式自动添加。</p>
        <details class="image-submitted">
          <summary>本次生成参数</summary>
          <p>{{ submitted?.prompt }}</p>
          <p class="image-muted">
            {{ submitted?.size || '默认尺寸' }} · {{ submitted?.quality || '默认质量' }} ·
            {{ submitted?.output_format || '默认格式' }}
          </p>
        </details>
        <p v-if="result.usage" class="image-muted">
          输入 {{ result.usage.input_tokens ?? '未知' }} · 输出
          {{ result.usage.output_tokens ?? '未知' }} · 总计
          {{ result.usage.total_tokens ?? '未知' }} tokens
        </p>
      </template>
    </section>
  </div>
</template>
