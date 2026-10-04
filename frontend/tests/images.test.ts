import { describe, expect, it } from 'vitest';
import {
  imageDownloadFilename,
  defaultImageDownloadName,
  imageSource,
  imageEditInputs,
  imageErrorMessage,
  imageInputSize,
  imageUploadMime,
  MAX_IMAGE_INPUT_BYTES,
  MAX_IMAGE_INPUT_TOTAL_BYTES,
  validateImageUpload,
  validateImageUploads,
} from '../src/domain/images';
import { ApiError } from '../src/api/client';

describe('image request errors', () => {
  const error = (detail: unknown, errorType = 'ValidationError') =>
    new ApiError('Invalid request', {
      status: 400,
      path: '/images/edits',
      requestId: null,
      errorType,
      detail,
    });
  it('shows the invalid field and image number without echoing image input', () => {
    const message = imageErrorMessage(
      error([
        {
          type: 'value_error',
          loc: ['body', 'request', 'images', 0],
          msg: 'Value error, Original image format does not match its MIME type',
          input: 'private-image-data',
        },
      ]),
    );
    expect(message).toBe(
      '图片请求参数无效：参考图 · 第 1 张：图片内容与格式声明不一致，请重新选择图片',
    );
    expect(message).not.toContain('private-image-data');
  });
  it('identifies the old single image backend schema', () => {
    expect(
      imageErrorMessage(
        error([
          { type: 'missing', loc: ['body', 'request', 'image'], msg: 'Field required' },
          {
            type: 'extra_forbidden',
            loc: ['body', 'request', 'images'],
            msg: 'Extra inputs are not permitted',
          },
        ]),
      ),
    ).toContain('前后端改图接口版本不一致');
  });
  it('distinguishes provider rejections and handles unavailable validation details', () => {
    expect(imageErrorMessage(error(null, 'ProviderRequestError'))).toBe(
      '服务商拒绝了图片请求：Invalid request',
    );
    expect(imageErrorMessage(error([null, {}, 'invalid']))).toBe('Invalid request');
    expect(imageErrorMessage(new Error('offline'))).toBe('offline');
  });
});

describe('image uploads', () => {
  it('accepts supported images up to the size limit', () => {
    for (const type of ['image/png', 'image/jpeg', 'image/webp']) {
      expect(() => validateImageUpload({ type, size: MAX_IMAGE_INPUT_BYTES })).not.toThrow();
    }
  });
  it('rejects empty and oversized files', () => {
    expect(() => validateImageUpload({ type: 'image/png', size: 0 })).toThrow('图片文件为空');
    expect(() =>
      validateImageUpload({ type: 'image/png', size: MAX_IMAGE_INPUT_BYTES + 1 }),
    ).toThrow('图片不能超过 20 MiB');
  });
  it('detects actual bitmap signatures and does not trust the browser MIME type', () => {
    for (const type of ['', 'application/octet-stream', 'image/png']) {
      expect(() => validateImageUpload({ type, size: 100 })).not.toThrow();
    }
    expect(imageUploadMime(new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]))).toBe('image/png');
    expect(imageUploadMime(new Uint8Array([255, 216, 255]))).toBe('image/jpeg');
    expect(imageUploadMime(new TextEncoder().encode('RIFFxxxxWEBP'))).toBe('image/webp');
    for (const value of ['', '<svg />', 'GIF89a', 'invalid', 'RIFFxxxxWAVE']) {
      expect(() => imageUploadMime(new TextEncoder().encode(value))).toThrow(
        '图片内容不是 PNG、JPEG 或 WebP',
      );
    }
  });
  it('limits both appended image count and total file sizes', () => {
    const file = { type: 'image/png', size: 10 };
    expect(() => validateImageUploads(Array(16).fill(file))).not.toThrow();
    expect(() => validateImageUploads([file], Array(16).fill(file))).toThrow(
      '最多上传 16 张参考图',
    );
    expect(() => validateImageUploads(Array(17).fill(file))).toThrow('最多上传 16 张参考图');
    expect(() =>
      validateImageUploads([{ ...file, size: 10 }], [{ size: MAX_IMAGE_INPUT_TOTAL_BYTES - 10 }]),
    ).not.toThrow();
    expect(() =>
      validateImageUploads([{ ...file, size: 11 }], [{ size: MAX_IMAGE_INPUT_TOTAL_BYTES - 10 }]),
    ).toThrow('参考图总大小不能超过 50 MiB');
  });
  it('restores ordered references and supports old single image records', () => {
    const first = { mime_type: 'image/png' as const, base64_data: 'AAAA' };
    const second = { mime_type: 'image/jpeg' as const, base64_data: 'AA==' };
    const request = { model_id: 'edit-model', prompt: 'Combine images' };
    expect(imageEditInputs({ ...request, images: [first, second] })).toEqual([first, second]);
    expect(imageEditInputs({ ...request, image: first })).toEqual([first]);
    expect(imageEditInputs(request)).toEqual([]);
    expect(imageInputSize(first)).toBe(3);
    expect(imageInputSize(second)).toBe(1);
    expect(imageInputSize({ ...first, base64_data: 'AAA=' })).toBe(2);
  });
});

describe('image sources', () => {
  it('accepts provider bitmaps and http URLs', () => {
    expect(imageSource({ base64_data: 'AAAA', mime_type: 'image/png' })).toBe(
      'data:image/png;base64,AAAA',
    );
    expect(imageSource({ url: 'https://images.example/a.png' })).toBe(
      'https://images.example/a.png',
    );
  });
  it('rejects unsafe URLs, credentials and unknown image formats', () => {
    for (const url of [
      'javascript:alert(1)',
      'data:text/html,hello',
      'file:///secret',
      'https://user:secret@images.example/a',
      'invalid',
    ])
      expect(imageSource({ url })).toBe('');
    expect(imageSource({ base64_data: 'AAAA' })).toBe('');
  });
});

describe('image download filenames', () => {
  it('includes image number and a padded local timestamp in default names', () => {
    const date = new Date(2026, 9, 5, 1, 3, 2, 7);
    expect(defaultImageDownloadName(0, date)).toBe('evernight-image-1_20261005_010302_007');
    expect(defaultImageDownloadName(1, date)).toBe('evernight-image-2_20261005_010302_007');
  });
  it('supports Chinese names and matches the actual bitmap format', () => {
    expect(imageDownloadFilename('  绿色叶子  ', 0, 'image/png')).toBe('绿色叶子.png');
    expect(imageDownloadFilename('作品.JPG', 0, 'image/png')).toBe('作品.png');
    expect(imageDownloadFilename('作品.png', 0, 'image/jpeg')).toBe('作品.jpg');
    expect(imageDownloadFilename('作品.webp', 0, 'image/webp')).toBe('作品.webp');
  });
  it('uses each image number when the name is blank', () => {
    for (const name of ['', '   ', '...', '.png'])
      expect(imageDownloadFilename(name, 1, 'image/png')).toMatch(
        /^evernight-image-2_\d{8}_\d{6}_\d{3}\.png$/,
      );
  });
  it('normalizes directory separators, control characters and reserved names', () => {
    expect(imageDownloadFilename('../作品\\叶子:1\n', 0, 'image/png')).toBe('_作品_叶子_1.png');
    expect(imageDownloadFilename('CON', 0, 'image/jpeg')).toBe('_CON.jpg');
    expect(imageDownloadFilename('aux.cover', 0, 'image/png')).toBe('_aux.cover.png');
    expect(imageDownloadFilename('LPT9.png', 0, 'image/png')).toBe('_LPT9.png');
  });
  it('rejects unsupported response formats', () => {
    expect(() => imageDownloadFilename('作品', 0, 'text/html')).toThrow(
      '返回内容不是支持的图片格式',
    );
  });
});
