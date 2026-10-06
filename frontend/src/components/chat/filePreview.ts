const htmlPreviewPolicy = [
  "default-src 'none'",
  "script-src 'unsafe-inline' 'unsafe-eval' https: blob:",
  "style-src 'unsafe-inline' https:",
  'img-src data: blob: https:',
  'font-src data: https:',
  'media-src data: blob: https:',
  "connect-src 'none'",
  "frame-src 'none'",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
].join('; ');

export async function htmlPreviewBlob(content: Blob): Promise<Blob> {
  const source = await content.text();
  const policy = `<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${htmlPreviewPolicy}"><meta name="referrer" content="no-referrer">`;
  return new Blob([policy, source], { type: 'text/html;charset=utf-8' });
}
