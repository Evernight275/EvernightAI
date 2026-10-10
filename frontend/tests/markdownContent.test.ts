import { createSSRApp } from 'vue';
import { renderToString } from '@vue/server-renderer';
import { describe, expect, it } from 'vitest';
import MarkdownContent from '../src/components/common/MarkdownContent.vue';
import { renderMarkdown, renderMarkdownBlocks } from '../src/components/common/markdownContent';

describe('Markdown content', () => {
  it('renders common chat Markdown structures', async () => {
    const source = [
      '## Result',
      '',
      '- first',
      '- second',
      '',
      '| Name | Value |',
      '| --- | --- |',
      '| count | 2 |',
      '',
      '```ts',
      'const count = 2',
      '```',
    ].join('\n');
    const html = await renderToString(createSSRApp(MarkdownContent, { source }));

    expect(html).toContain('<h2>Result</h2>');
    expect(html).toContain('<ul>');
    expect(html).toContain('<table>');
    expect(html).toContain('class="markdown-code-block"');
    expect(html).toContain('TypeScript');
    expect(html).toContain('data-copy-code');
    expect(html).toContain('<code class="language-ts">');
    expect(html).toContain('hljs-keyword');
  });

  it('highlights common model code fences and safely falls back', () => {
    const python = renderMarkdown('```python\nfor item in items:\n    print(item)\n```');
    const matlab = renderMarkdown('```matlab\nfor index = 1:10\nend\n```');
    const unknown = renderMarkdown('```unknown\n<script>alert(1)</script>\n```');

    expect(python).toContain('Python');
    expect(python).toContain('hljs-keyword');
    expect(matlab).toContain('MATLAB');
    expect(matlab).toContain('hljs-keyword');
    expect(unknown).toContain('unknown');
    expect(unknown).not.toContain('<script>');
    expect(unknown).toContain('&lt;script&gt;');
  });

  it('numbers code lines, keeps multi-line tokens balanced and offers wrapping', () => {
    const html = renderMarkdown('```python\n"""doc\nstring"""\nvalue = 1\n```');

    expect(html).toContain('markdown-code-block--numbered');
    expect(html).toContain('--code-digits: 1');
    expect(html.match(/class="code-line"/g)).toHaveLength(3);
    expect(html).toContain(
      '<span class="code-line"><span class="hljs-string">&quot;&quot;&quot;doc\n</span></span>' +
        '<span class="code-line"><span class="hljs-string">string&quot;&quot;&quot;</span>\n</span>',
    );
    expect(html).toContain('data-wrap-code');
    expect(html).toContain('aria-pressed="false"');
    expect(renderMarkdown('```\none line\n```')).not.toContain('markdown-code-block--numbered');
  });

  it('labels and highlights additional languages and aliases', () => {
    expect(renderMarkdown('```rs\nfn main() {}\n```')).toContain('Rust');
    expect(renderMarkdown('```rs\nfn main() {}\n```')).toContain('hljs-keyword');
    expect(renderMarkdown('```yml\nkey: value\n```')).toContain('YAML');
    expect(renderMarkdown('```toml\nkey = "value"\n```')).toContain('INI / TOML');
    expect(renderMarkdown('```diff\n-old\n+new\n```')).toContain('hljs-addition');
  });

  it('marks only closed Mermaid fences for drawing and keeps the source escaped', () => {
    const source = '```mermaid\ngraph TD\n  A["<b>x</b>"] --> B\n```';
    const closed = renderMarkdown(`Intro\n\n${source}\n\nAfter`);
    const nested = renderMarkdown(`- item\n\n  ${source.replaceAll('\n', '\n  ')}\n`);
    const streaming = renderMarkdown('```mermaid\ngraph TD\n  A --> B\n');
    const streamingPartialClose = renderMarkdown('```mermaid\ngraph TD\n  A --> B\n``');

    expect(closed).toContain('data-mermaid-ready');
    expect(closed).toContain('Mermaid');
    expect(closed).toContain('data-mermaid-toggle');
    expect(closed).toContain('data-copy-code');
    expect(closed).toContain('&lt;b&gt;x&lt;/b&gt;');
    expect(closed).not.toContain('<b>x</b>');
    expect(nested).toContain('data-mermaid-ready');
    expect(streaming).toContain('markdown-mermaid');
    expect(streaming).not.toContain('data-mermaid-ready');
    expect(streamingPartialClose).not.toContain('data-mermaid-ready');
    expect(renderMarkdown('```python\nx = 1\n```')).not.toContain('markdown-mermaid');
  });

  it('reuses unchanged blocks while a message is streamed', () => {
    const first = new Map<string, string>();
    const start = '# Title\n\nSee [the docs][docs].\n\n```python\nx = 1\n```\n\nTail';
    const before = renderMarkdownBlocks(start, undefined, first);
    expect(before).toHaveLength(4);
    expect(before.join('')).toBe(renderMarkdown(start));

    const marked = new Map([...first].map(([key, html]) => [key, html + '<!--kept-->']));
    const second = new Map<string, string>();
    const after = renderMarkdownBlocks(start + ' grows', marked, second);
    expect(after.slice(0, 3).every((html) => html.endsWith('<!--kept-->'))).toBe(true);
    expect(after[3]).toBe('<p>Tail grows</p>\n');
    expect(second.size).toBe(4);

    const linked = renderMarkdownBlocks(start + '\n\n[docs]: https://example.com/docs', marked);
    expect(linked[1]).toContain('href="https://example.com/docs"');
    expect(linked[1]).not.toContain('<!--kept-->');
    expect(linked[0]).not.toContain('<!--kept-->');
  });

  it('hides half-streamed fence edges', () => {
    const label = (source: string) =>
      /markdown-code-language">([^<]*)</.exec(renderMarkdown(source))?.[1];
    expect(label('```p')).toBe('代码');
    expect(label('```pyt')).toBe('代码');
    expect(label('```python\n')).toBe('代码');
    expect(label('```python\nx')).toBe('Python');
    expect(label('```python\n```')).toBe('Python');

    const closing = renderMarkdown('```python\nx = 1\n``');
    expect(closing.match(/class="code-line"/g)).toHaveLength(1);
    expect(closing).not.toContain('``');
    expect(renderMarkdown('~~~text\na\n~')).not.toContain('~');
    expect(renderMarkdown('```text\na\n``\nb\n```')).toContain('``');
  });

  it('disables raw HTML in model output', () => {
    const html = renderMarkdown('<script>alert("unsafe")</script>');

    expect(html).not.toContain('<script>');
    expect(html).toContain('&lt;script&gt;');
  });

  it('rejects unsafe links and secures normal external links', () => {
    const unsafe = renderMarkdown('[bad](javascript:alert(1))');
    const safe = renderMarkdown('[docs](https://example.com/docs)');

    expect(unsafe).not.toContain('href="javascript:');
    expect(safe).toContain('target="_blank"');
    expect(safe).toContain('rel="noopener noreferrer"');
  });

  it('renders inline and block formulas with KaTeX', () => {
    const inline = renderMarkdown('Euler: $e^{i\\pi} + 1 = 0$.');
    const block = renderMarkdown('$$\\int_0^1 x^2 \\, dx = \\frac{1}{3}$$');

    expect(inline).toContain('<span class="katex">');
    expect(inline).not.toContain('katex-display');
    expect(block).toContain("<p class='katex-block'>");
    expect(block).toContain('<span class="katex-display">');
  });

  it('renders bracket-delimited formulas commonly returned by models', () => {
    const inline = renderMarkdown('速度为 \\(v = \\frac{dx}{dt}\\)。');
    const block = renderMarkdown(
      [
        '\\[',
        '\\boxed{',
        '-\\frac{d}{dx}\\left(kA\\frac{dT}{dx}\\right)',
        '\\dot q A',
        '}',
        '\\]',
      ].join('\n'),
    );

    expect(inline).toContain('<span class="katex">');
    expect(inline).not.toContain('\\(v =');
    expect(block).toContain("<p class='katex-block'>");
    expect(block).toContain('<span class="katex-display">');
    expect(block).toContain('<menclose notation="box">');
    expect(block).not.toContain('<p>[</p>');
  });

  it('keeps rendering when a formula is invalid', () => {
    const html = renderMarkdown('Before $\\notacommand{$ after');

    expect(html).toContain('Before');
    expect(html).toContain('katex-error');
  });

  it('does not trust links embedded in formulas', () => {
    const html = renderMarkdown('$\\href{javascript:alert(1)}{unsafe}$');

    expect(html).not.toContain('href="javascript:');
    expect(html).not.toContain('<a ');
    expect(html).toContain('<mtext>\\href</mtext>');
  });
});
