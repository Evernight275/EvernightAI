import { createSSRApp } from 'vue';
import { renderToString } from '@vue/server-renderer';
import { describe, expect, it } from 'vitest';
import JsonCode from '../src/components/common/JsonCode.vue';
import { renderJson } from '../src/components/common/jsonContent';

describe('Tool JSON content', () => {
  it('preserves original whitespace, key order and numeric precision', () => {
    const source = '  {\n "z": 9007199254740993, "a": 1.2300, "ok": true, "value": null\n}\n';
    const html = renderJson(source);
    expect(html.replace(/<[^>]*>/g, '').replaceAll('&quot;', '"')).toBe(source);
    expect(html).toContain('hljs-attr');
    expect(html).toContain('hljs-number');
    expect(html).toContain('hljs-literal');
  });

  it.each([
    '{"content":"<img src=x onerror=alert(1)> &lt;script&gt;"}',
    'Failed: <script>alert("unsafe")</script> &lt;img&gt;',
    '{"content": "<img src=x onerror=alert(1)>',
    '<img src=x onerror=alert(1)>'.repeat(5000),
  ])('escapes tool output in highlighted and plain text paths', async (source) => {
    const html = await renderToString(createSSRApp(JsonCode, { source }));
    expect(html).not.toContain('<img');
    expect(html).not.toContain('<script');
    expect(html).toContain('&lt;');
    const text = html
      .replace(/<[^>]*>/g, '')
      .replaceAll('&lt;', '<')
      .replaceAll('&gt;', '>')
      .replaceAll('&quot;', '"')
      .replaceAll('&#x27;', "'")
      .replaceAll('&#39;', "'")
      .replaceAll('&amp;', '&');
    expect(text).toBe(source);
  });
});
