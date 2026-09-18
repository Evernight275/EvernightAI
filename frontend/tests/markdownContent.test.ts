import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'
import MarkdownContent from '../src/components/common/MarkdownContent.vue'
import { renderMarkdown } from '../src/components/common/markdownContent'

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
    ].join('\n')
    const html = await renderToString(createSSRApp(MarkdownContent, { source }))

    expect(html).toContain('<h2>Result</h2>')
    expect(html).toContain('<ul>')
    expect(html).toContain('<table>')
    expect(html).toContain('class="markdown-code-block"')
    expect(html).toContain('TypeScript')
    expect(html).toContain('data-copy-code')
    expect(html).toContain('<code class="language-ts">')
    expect(html).toContain('hljs-keyword')
  })

  it('highlights common model code fences and safely falls back', () => {
    const python = renderMarkdown('```python\nfor item in items:\n    print(item)\n```')
    const matlab = renderMarkdown('```matlab\nfor index = 1:10\nend\n```')
    const unknown = renderMarkdown('```unknown\n<script>alert(1)</script>\n```')

    expect(python).toContain('Python')
    expect(python).toContain('hljs-keyword')
    expect(matlab).toContain('MATLAB')
    expect(matlab).toContain('hljs-keyword')
    expect(unknown).toContain('unknown')
    expect(unknown).not.toContain('<script>')
    expect(unknown).toContain('&lt;script&gt;')
  })

  it('disables raw HTML in model output', () => {
    const html = renderMarkdown('<script>alert("unsafe")</script>')

    expect(html).not.toContain('<script>')
    expect(html).toContain('&lt;script&gt;')
  })

  it('rejects unsafe links and secures normal external links', () => {
    const unsafe = renderMarkdown('[bad](javascript:alert(1))')
    const safe = renderMarkdown('[docs](https://example.com/docs)')

    expect(unsafe).not.toContain('href="javascript:')
    expect(safe).toContain('target="_blank"')
    expect(safe).toContain('rel="noopener noreferrer"')
  })

  it('renders inline and block formulas with KaTeX', () => {
    const inline = renderMarkdown('Euler: $e^{i\\pi} + 1 = 0$.')
    const block = renderMarkdown('$$\\int_0^1 x^2 \\, dx = \\frac{1}{3}$$')

    expect(inline).toContain('<span class="katex">')
    expect(inline).not.toContain('katex-display')
    expect(block).toContain("<p class='katex-block'>")
    expect(block).toContain('<span class="katex-display">')
  })

  it('renders bracket-delimited formulas commonly returned by models', () => {
    const inline = renderMarkdown('速度为 \\(v = \\frac{dx}{dt}\\)。')
    const block = renderMarkdown([
      '\\[',
      '\\boxed{',
      '-\\frac{d}{dx}\\left(kA\\frac{dT}{dx}\\right)',
      '\\dot q A',
      '}',
      '\\]',
    ].join('\n'))

    expect(inline).toContain('<span class="katex">')
    expect(inline).not.toContain('\\(v =')
    expect(block).toContain("<p class='katex-block'>")
    expect(block).toContain('<span class="katex-display">')
    expect(block).toContain('<menclose notation="box">')
    expect(block).not.toContain('<p>[</p>')
  })

  it('keeps rendering when a formula is invalid', () => {
    const html = renderMarkdown('Before $\\notacommand{$ after')

    expect(html).toContain('Before')
    expect(html).toContain('katex-error')
  })

  it('does not trust links embedded in formulas', () => {
    const html = renderMarkdown('$\\href{javascript:alert(1)}{unsafe}$')

    expect(html).not.toContain('href="javascript:')
    expect(html).not.toContain('<a ')
    expect(html).toContain('<mtext>\\href</mtext>')
  })
})
