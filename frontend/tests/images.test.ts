import { describe, expect, it } from 'vitest'
import { imageSource } from '../src/domain/images'

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
