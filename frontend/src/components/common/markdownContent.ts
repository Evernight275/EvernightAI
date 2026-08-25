import { katex } from '@mdit/plugin-katex'
import MarkdownIt from 'markdown-it'
import { computed, type ComputedRef } from 'vue'

export type MarkdownContentProps = {
  source: string
}

const markdown = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: true,
  typographer: false,
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

export function useMarkdownContent(
  props: MarkdownContentProps,
): { html: ComputedRef<string> } {
  return {
    html: computed(() => renderMarkdown(props.source)),
  }
}

export function renderMarkdown(source: string): string {
  return markdown.render(source)
}
