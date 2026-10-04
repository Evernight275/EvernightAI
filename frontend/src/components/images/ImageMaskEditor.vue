<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue';
import type { ImageEditInput, ImageMaskInput } from '../../api/images';
import { imageInputSize, imageSource, MAX_IMAGE_INPUT_BYTES } from '../../domain/images';

const props = defineProps<{
  image: ImageEditInput;
  initialMask?: ImageMaskInput | null;
  disabled?: boolean;
}>();
const emit = defineEmits<{
  change: [value: { image: ImageEditInput; mask: ImageMaskInput } | null];
  busy: [value: boolean];
}>();
const canvas = ref<HTMLCanvasElement | null>(null);
const brush = ref(32);
const eraser = ref(false);
const error = ref('');
let maskCanvas: HTMLCanvasElement | null = null;
let source: ImageEditInput | null = null;
let previous: { x: number; y: number } | null = null;
let pointer: number | null = null;
let version = 0;
let ready = false;

function overlay(): void {
  if (!canvas.value || !maskCanvas) return;
  const ctx = canvas.value.getContext('2d')!;
  ctx.clearRect(0, 0, canvas.value.width, canvas.value.height);
  ctx.globalCompositeOperation = 'source-over';
  ctx.fillStyle = 'rgba(215, 67, 112, .5)';
  ctx.fillRect(0, 0, canvas.value.width, canvas.value.height);
  ctx.globalCompositeOperation = 'destination-out';
  ctx.drawImage(maskCanvas, 0, 0);
  ctx.globalCompositeOperation = 'source-over';
}
function publish(): void {
  if (!maskCanvas || !source || !ready) return;
  const mask: ImageMaskInput = {
    base64_data: maskCanvas.toDataURL('image/png').split(',')[1]!,
    mime_type: 'image/png',
  };
  if (imageInputSize(mask) > MAX_IMAGE_INPUT_BYTES) {
    error.value = '遮罩超过 20 MiB，请使用较小的图片';
    emit('change', null);
    return;
  }
  emit('change', { image: source, mask });
}
function clear(): void {
  if (!maskCanvas || props.disabled) return;
  const ctx = maskCanvas.getContext('2d')!;
  ctx.globalCompositeOperation = 'source-over';
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, maskCanvas.width, maskCanvas.height);
  overlay();
  emit('change', null);
}
watch(
  () => [props.image, props.initialMask] as const,
  async ([input, initialMask]) => {
    const current = ++version;
    ready = false;
    previous = null;
    pointer = null;
    emit('change', null);
    emit('busy', true);
    error.value = '';
    try {
      await nextTick();
      const image = new Image();
      image.src = imageSource(input);
      await image.decode();
      if (current !== version || !canvas.value) return;
      if (image.naturalWidth * image.naturalHeight > 32_000_000)
        throw new Error('图片过大，局部改图最多支持 3200 万像素');
      const original = document.createElement('canvas');
      original.width = image.naturalWidth;
      original.height = image.naturalHeight;
      original.getContext('2d')!.drawImage(image, 0, 0);
      source = {
        base64_data: original.toDataURL('image/png').split(',')[1]!,
        mime_type: 'image/png',
      };
      if (imageInputSize(source) > MAX_IMAGE_INPUT_BYTES)
        throw new Error('图片转换为 PNG 后超过 20 MiB，请使用较小的图片');
      canvas.value.width = original.width;
      canvas.value.height = original.height;
      maskCanvas = document.createElement('canvas');
      maskCanvas.width = original.width;
      maskCanvas.height = original.height;
      const ctx = maskCanvas.getContext('2d')!;
      ctx.fillStyle = '#000';
      ctx.fillRect(0, 0, original.width, original.height);
      if (initialMask) {
        const mask = new Image();
        mask.src = imageSource(initialMask);
        await mask.decode();
        if (current !== version) return;
        if (mask.naturalWidth !== original.width || mask.naturalHeight !== original.height)
          throw new Error('遮罩尺寸与参考图不一致');
        ctx.clearRect(0, 0, original.width, original.height);
        ctx.drawImage(mask, 0, 0);
      }
      ready = true;
      overlay();
      if (initialMask) publish();
    } catch (cause) {
      if (current === version)
        error.value = cause instanceof Error ? cause.message : '无法打开局部改图画布';
    } finally {
      if (current === version) emit('busy', false);
    }
  },
  { immediate: true },
);
function draw(event: PointerEvent): void {
  if (props.disabled || !ready || !maskCanvas || !canvas.value || pointer !== event.pointerId)
    return;
  const rect = canvas.value.getBoundingClientRect();
  const point = {
    x: ((event.clientX - rect.left) * maskCanvas.width) / rect.width,
    y: ((event.clientY - rect.top) * maskCanvas.height) / rect.height,
  };
  const ctx = maskCanvas.getContext('2d')!;
  ctx.globalCompositeOperation = eraser.value ? 'source-over' : 'destination-out';
  ctx.strokeStyle = '#000';
  ctx.fillStyle = '#000';
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.lineWidth = (brush.value * maskCanvas.width) / rect.width;
  ctx.beginPath();
  ctx.moveTo(previous?.x ?? point.x, previous?.y ?? point.y);
  ctx.lineTo(point.x, point.y);
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(point.x, point.y, ctx.lineWidth / 2, 0, Math.PI * 2);
  ctx.fill();
  previous = point;
  overlay();
}
function start(event: PointerEvent): void {
  if (props.disabled || !ready || pointer !== null || event.button !== 0) return;
  pointer = event.pointerId;
  canvas.value?.setPointerCapture(event.pointerId);
  draw(event);
}
function end(event: PointerEvent): void {
  if (pointer !== event.pointerId) return;
  if (canvas.value?.hasPointerCapture(event.pointerId))
    canvas.value.releasePointerCapture(event.pointerId);
  previous = null;
  pointer = null;
  publish();
}
onBeforeUnmount(() => {
  version++;
  emit('busy', false);
});
</script>
<template>
  <section class="image-mask-editor" aria-label="局部改图">
    <p class="image-muted">
      在图 1 上涂抹需要修改的区域，再描述修改要求。遮罩用于引导模型，边界可能略有变化。
    </p>
    <div class="image-mask-tools">
      <label
        >笔刷<input
          v-model.number="brush"
          type="range"
          min="4"
          max="100"
          :disabled="disabled"
          aria-label="笔刷大小"
      /></label>
      <button type="button" :aria-pressed="eraser" :disabled="disabled" @click="eraser = !eraser">
        {{ eraser ? '恢复区域' : '涂抹区域' }}
      </button>
      <button type="button" :disabled="disabled" @click="clear">清除涂抹</button>
    </div>
    <div class="image-mask-canvas">
      <img :src="imageSource(image)" alt="局部改图参考图" />
      <canvas
        ref="canvas"
        aria-label="涂抹修改区域"
        @pointerdown="start"
        @pointermove="draw"
        @pointerup="end"
        @pointercancel="end"
      />
    </div>
    <p v-if="error" class="image-error" role="alert">{{ error }}</p>
  </section>
</template>
