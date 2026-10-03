import type { GeneratedImage } from '../api/images'

export function imageSource(image: GeneratedImage): string {
  if (image.base64_data && ['image/png', 'image/jpeg', 'image/webp'].includes(image.mime_type || '')) {
    return `data:${image.mime_type};base64,${image.base64_data}`
  }
  if (image.url) {
    try {
      const url = new URL(image.url)
      if (['http:', 'https:'].includes(url.protocol) && !url.username && !url.password) return url.href
    } catch { /* Invalid provider URL. */ }
  }
  return ''
}

export function imageDownloadFilename(name: string, index: number, mimeType: string): string {
  const extension = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp' }[mimeType]
  if (!extension) throw new Error('返回内容不是支持的图片格式')
  let base = name.trim().replace(/\.(png|jpe?g|webp)$/i, '')
    .replace(/[<>:"/\\|?*\u0000-\u001f\u007f]/g, '_').replace(/^[. ]+|[. ]+$/g, '')
  if (!base) base = `evernight-image-${index + 1}`
  if (/^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(base)) base = `_${base}`
  return `${base}.${extension}`
}

export async function downloadImage(image: GeneratedImage, index: number, signal?: AbortSignal, name = ''): Promise<void> {
  const source = imageSource(image)
  if (!source) throw new Error('图片地址无效')
  const response = await fetch(source, { credentials: 'omit', referrerPolicy: 'no-referrer', signal })
  if (!response.ok) throw new Error('下载失败，可打开原图保存')
  const blob = await response.blob()
  signal?.throwIfAborted()
  const filename = imageDownloadFilename(name, index, blob.type)
  const url = URL.createObjectURL(blob)
  try {
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.click()
  } finally { setTimeout(() => URL.revokeObjectURL(url), 1000) }
}
