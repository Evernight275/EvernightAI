import { katex } from '@mdit/plugin-katex'
import highlighter from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import css from 'highlight.js/lib/languages/css'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import matlab from 'highlight.js/lib/languages/matlab'
import python from 'highlight.js/lib/languages/python'
import sql from 'highlight.js/lib/languages/sql'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import MarkdownIt from 'markdown-it'
import { computed, type ComputedRef } from 'vue'

export type MarkdownContentProps = {
  source: string
}

const languages = {
  bash,
  css,
  javascript,
  json,
  matlab,
  python,
  sql,
  typescript,
  xml,
}

Object.entries(languages).forEach(([name, language]) => {
  highlighter.registerLanguage(name, language)
})

const languageAliases: Record<string, string> = {
  html: 'xml',
  js: 'javascript',
  jsx: 'javascript',
  py: 'python',
  sh: 'bash',
  shell: 'bash',
  ts: 'typescript',
  tsx: 'typescript',
}

const languageLabels: Record<string, string> = {
  bash: 'Shell',
  css: 'CSS',
  javascript: 'JavaScript',
  json: 'JSON',
  matlab: 'MATLAB',
  python: 'Python',
  sql: 'SQL',
  typescript: 'TypeScript',
  xml: 'HTML / XML',
}

const markdown = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: true,
  typographer: false,
  highlight(source, language) {
    const normalized = normalizeLanguage(language)
    if (!normalized || !highlighter.getLanguage(normalized)) {
      return escapeHtml(source)
    }
    return highlighter.highlight(source, {
      language: normalized,
      ignoreIllegals: true,
    }).value
  },
})

markdown.use(katex, {
  delimiters: 'all',
  throwOnError: false,
  trust: false,
})

const defaultLinkOpen = markdown.renderer.rules.link_open
markdown.renderer.rules.link_open = (tokens, index, options, env, renderer) => {
  tokens[index]?.attrSet('target', '_blank')
  tokens[index]?.attrSet('rel', 'noopener noreferrer')
  return defaultLinkOpen
    ? defaultLinkOpen(tokens, index, options, env, renderer)
    : renderer.renderToken(tokens, index, options)
}

const defaultFence = markdown.renderer.rules.fence
markdown.renderer.rules.fence = (tokens, index, options, env, renderer) => {
  const language = normalizeLanguage(tokens[index]?.info || '')
  const label = languageLabels[language] || language || '代码'
  const fence = defaultFence
    ? defaultFence(tokens, index, options, env, renderer)
    : renderer.renderToken(tokens, index, options)
  return [
    '<div class="markdown-code-block">',
    '<div class="markdown-code-header">',
    `<span>${escapeHtml(label)}</span>`,
    '<button type="button" data-copy-code>复制</button>',
    '</div>',
    fence,
    '</div>',
  ].join('')
}

export function useMarkdownContent(
  props: MarkdownContentProps,
): {
  html: ComputedRef<string>
  copyCode: (event: MouseEvent) => Promise<void>
} {
  return {
    html: computed(() => renderMarkdown(props.source)),
    copyCode: copyMarkdownCode,
  }
}

export function renderMarkdown(source: string): string {
  return markdown.render(source)
}

export async function copyMarkdownCode(event: MouseEvent): Promise<void> {
  const target = event.target
  if (!(target instanceof Element)) {
    return
  }
  const button = target.closest<HTMLButtonElement>('[data-copy-code]')
  const code = button?.closest('.markdown-code-block')?.querySelector('code')
  if (!button || !code?.textContent) {
    return
  }
  try {
    await navigator.clipboard.writeText(code.textContent)
    showCopyResult(button, '已复制')
  } catch {
    showCopyResult(button, '复制失败')
  }
}

function normalizeLanguage(value: string): string {
  const language = value.trim().split(/\s+/, 1)[0]?.toLowerCase() || ''
  return languageAliases[language] || language
}

function showCopyResult(button: HTMLButtonElement, label: string): void {
  button.textContent = label
  window.setTimeout(() => {
    button.textContent = '复制'
  }, 1600)
}

function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
}
