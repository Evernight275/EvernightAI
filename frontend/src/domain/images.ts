import type { GeneratedImage, ImageEditInput, ImageGenerationRecord } from '../api/images';
import { ApiError } from '../api/client';

export const MAX_IMAGE_INPUT_BYTES = 20 * 1024 * 1024;
export const MAX_IMAGE_INPUT_COUNT = 16;
export const MAX_IMAGE_INPUT_TOTAL_BYTES = 50 * 1024 * 1024;

export function imageErrorMessage(cause: unknown): string {
  if (!(cause instanceof ApiError))
    return cause instanceof Error ? cause.message : '生成失败，请重试';
  if (cause.errorType === 'ProviderRequestError') return `服务商拒绝了图片请求：${cause.message}`;
  if (cause.errorType !== 'ValidationError' || !Array.isArray(cause.detail)) return cause.message;
  const details = cause.detail.filter(
    (item): item is { type?: string; loc: (string | number)[]; msg: string } =>
      item !== null &&
      typeof item === 'object' &&
      Array.isArray(item.loc) &&
      typeof item.msg === 'string',
  );
  if (
    details.some(
      (item) => item.type === 'missing' && item.loc.join('.') === 'body.request.image',
    ) &&
    details.some(
      (item) => item.type === 'extra_forbidden' && item.loc.join('.') === 'body.request.images',
    )
  ) {
    return '前后端改图接口版本不一致，请重启后端并刷新页面。';
  }
  const labels: Record<string, string> = {
    provider_id: '服务商',
    model_id: '模型',
    prompt: '修改要求',
    count: '数量',
    size: '尺寸',
    quality: '质量',
    timeout_seconds: '超时时间',
    output_format: '文件格式',
    background: '背景',
    result_format: '返回方式',
    images: '参考图',
    image: '参考图',
    mime_type: '图片格式',
    base64_data: '图片数据',
  };
  const reasons: Record<string, string> = {
    'Original image format does not match its MIME type':
      '图片内容与格式声明不一致，请重新选择图片',
    'Original image must contain valid Base64 data': '图片数据无效，请重新选择图片',
    'Original image must not exceed 20 MiB': '单张图片不能超过 20 MiB',
    'Reference images must not exceed 50 MiB in total': '参考图总大小不能超过 50 MiB',
  };
  const messages = details.slice(0, 3).map((item) => {
    const field = item.loc
      .filter((part) => part !== 'body' && part !== 'request')
      .map((part) => (typeof part === 'number' ? `第 ${part + 1} 张` : labels[part] || '参数'))
      .join(' · ');
    const reason = item.msg.replace(/^Value error, /, '');
    return `${field || '请求参数'}：${reasons[reason] || reason}`;
  });
  return messages.length ? `图片请求参数无效：${messages.join('；')}` : cause.message;
}

export function imageInputSize(image: ImageEditInput): number {
  return (
    (image.base64_data.length * 3) / 4 -
    (image.base64_data.endsWith('==') ? 2 : image.base64_data.endsWith('=') ? 1 : 0)
  );
}

export function imageEditInputs(request: ImageGenerationRecord['request']): ImageEditInput[] {
  if ('images' in request) return request.images;
  if ('image' in request) return [request.image];
  return [];
}

export function validateImageUploads(
  files: Pick<File, 'size' | 'type'>[],
  existing: { size: number }[] = [],
): void {
  if (files.length + existing.length > MAX_IMAGE_INPUT_COUNT)
    throw new Error('最多上传 16 张参考图');
  files.forEach(validateImageUpload);
  if (
    [...existing, ...files].reduce((total, file) => total + file.size, 0) >
    MAX_IMAGE_INPUT_TOTAL_BYTES
  )
    throw new Error('参考图总大小不能超过 50 MiB');
}

export function validateImageUpload(file: Pick<File, 'size' | 'type'>): void {
  if (!file.size) throw new Error('图片文件为空');
  if (file.size > MAX_IMAGE_INPUT_BYTES) throw new Error('图片不能超过 20 MiB');
}

export function imageUploadMime(header: Uint8Array): ImageEditInput['mime_type'] {
  if ([137, 80, 78, 71, 13, 10, 26, 10].every((byte, index) => header[index] === byte))
    return 'image/png';
  if (header[0] === 255 && header[1] === 216 && header[2] === 255) return 'image/jpeg';
  if (
    [82, 73, 70, 70].every((byte, index) => header[index] === byte) &&
    [87, 69, 66, 80].every((byte, index) => header[index + 8] === byte)
  )
    return 'image/webp';
  throw new Error('图片内容不是 PNG、JPEG 或 WebP，请选择支持的图片文件');
}

export async function readImageUpload(file: File, signal: AbortSignal): Promise<ImageEditInput> {
  validateImageUpload(file);
  signal.throwIfAborted();
  const source = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    const abort = (): void => reader.abort();
    const cleanup = (): void => signal.removeEventListener('abort', abort);
    reader.onload = () => {
      cleanup();
      resolve(String(reader.result));
    };
    reader.onerror = () => {
      cleanup();
      reject(new Error('无法读取图片，请重新选择'));
    };
    reader.onabort = () => {
      cleanup();
      reject(new DOMException('Aborted', 'AbortError'));
    };
    signal.addEventListener('abort', abort, { once: true });
    reader.readAsDataURL(file);
  });
  signal.throwIfAborted();
  const base64Data = source.slice(source.indexOf(',') + 1);
  const header = Uint8Array.from(atob(base64Data.slice(0, 24)), (char) => char.charCodeAt(0));
  const mimeType = imageUploadMime(header);
  const image = new Image();
  image.src = `data:${mimeType};base64,${base64Data}`;
  try {
    await image.decode();
  } catch {
    throw new Error('图片无法打开，请选择有效的图片文件');
  }
  signal.throwIfAborted();
  return { base64_data: base64Data, mime_type: mimeType };
}

export function imageSource(image: GeneratedImage): string {
  if (
    image.base64_data &&
    ['image/png', 'image/jpeg', 'image/webp'].includes(image.mime_type || '')
  ) {
    return `data:${image.mime_type};base64,${image.base64_data}`;
  }
  if (image.url) {
    try {
      const url = new URL(image.url);
      if (['http:', 'https:'].includes(url.protocol) && !url.username && !url.password)
        return url.href;
    } catch {
      /* Invalid provider URL. */
    }
  }
  return '';
}

export function defaultImageDownloadName(index: number, date = new Date()): string {
  const pad = (value: number, length = 2): string => String(value).padStart(length, '0');
  const day = `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}`;
  const time = `${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
  return `evernight-image-${index + 1}_${day}_${time}_${pad(date.getMilliseconds(), 3)}`;
}

export function imageDownloadFilename(name: string, index: number, mimeType: string): string {
  const extension = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp' }[mimeType];
  if (!extension) throw new Error('返回内容不是支持的图片格式');
  let base = name
    .trim()
    .replace(/\.(png|jpe?g|webp)$/i, '')
    .replace(/[<>:"/\\|?*\u0000-\u001f\u007f]/g, '_')
    .replace(/^[. ]+|[. ]+$/g, '');
  if (!base) base = defaultImageDownloadName(index);
  if (/^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(base)) base = `_${base}`;
  return `${base}.${extension}`;
}

export async function downloadImage(
  image: GeneratedImage,
  index: number,
  signal?: AbortSignal,
  name = '',
): Promise<void> {
  const source = imageSource(image);
  if (!source) throw new Error('图片地址无效');
  const response = await fetch(source, {
    credentials: 'omit',
    referrerPolicy: 'no-referrer',
    signal,
  });
  if (!response.ok) throw new Error('下载失败，可打开原图保存');
  const blob = await response.blob();
  signal?.throwIfAborted();
  const filename = imageDownloadFilename(name, index, blob.type);
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
