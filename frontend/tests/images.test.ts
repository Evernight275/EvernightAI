import { describe, expect, it } from 'vitest'
import { imageDownloadFilename, imageSource } from '../src/domain/images'

describe('image sources', () => {
  it('accepts provider bitmaps and http URLs', () => {
    expect(imageSource({ base64_data: 'AAAA', mime_type: 'image/png' })).toBe('data:image/png;base64,AAAA')
    expect(imageSource({ url: 'https://images.example/a.png' })).toBe('https://images.example/a.png')
  })
  it('rejects unsafe URLs, credentials and unknown image formats', () => {
    for (const url of ['javascript:alert(1)', 'data:text/html,hello', 'file:///secret', 'https://user:secret@images.example/a', 'invalid']) expect(imageSource({ url })).toBe('')
    expect(imageSource({ base64_data: 'AAAA' })).toBe('')
  })
})

describe('image download filenames', () => {
  it('supports Chinese names and matches the actual bitmap format', () => {
    expect(imageDownloadFilename('  绿色叶子  ', 0, 'image/png')).toBe('绿色叶子.png')
    expect(imageDownloadFilename('作品.JPG', 0, 'image/png')).toBe('作品.png')
    expect(imageDownloadFilename('作品.png', 0, 'image/jpeg')).toBe('作品.jpg')
    expect(imageDownloadFilename('作品.webp', 0, 'image/webp')).toBe('作品.webp')
  })
  it('uses each image number when the name is blank', () => {
    for (const name of ['', '   ', '...', '.png']) expect(imageDownloadFilename(name, 1, 'image/png')).toBe('evernight-image-2.png')
  })
  it('normalizes directory separators, control characters and reserved names', () => {
    expect(imageDownloadFilename('../作品\\叶子:1\n', 0, 'image/png')).toBe('_作品_叶子_1.png')
    expect(imageDownloadFilename('CON', 0, 'image/jpeg')).toBe('_CON.jpg')
    expect(imageDownloadFilename('aux.cover', 0, 'image/png')).toBe('_aux.cover.png')
    expect(imageDownloadFilename('LPT9.png', 0, 'image/png')).toBe('_LPT9.png')
  })
  it('rejects unsupported response formats', () => {
    expect(() => imageDownloadFilename('作品', 0, 'text/html')).toThrow('返回内容不是支持的图片格式')
  })
})
