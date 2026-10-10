import { katex } from '@mdit/plugin-katex';
import highlighter from 'highlight.js/lib/core';
import bash from 'highlight.js/lib/languages/bash';
import c from 'highlight.js/lib/languages/c';
import cpp from 'highlight.js/lib/languages/cpp';
import csharp from 'highlight.js/lib/languages/csharp';
import css from 'highlight.js/lib/languages/css';
import diff from 'highlight.js/lib/languages/diff';
import dockerfile from 'highlight.js/lib/languages/dockerfile';
import go from 'highlight.js/lib/languages/go';
import ini from 'highlight.js/lib/languages/ini';
import java from 'highlight.js/lib/languages/java';
import javascript from 'highlight.js/lib/languages/javascript';
import json from 'highlight.js/lib/languages/json';
import kotlin from 'highlight.js/lib/languages/kotlin';
import markdownLanguage from 'highlight.js/lib/languages/markdown';
import matlab from 'highlight.js/lib/languages/matlab';
import php from 'highlight.js/lib/languages/php';
import powershell from 'highlight.js/lib/languages/powershell';
import python from 'highlight.js/lib/languages/python';
import ruby from 'highlight.js/lib/languages/ruby';
import rust from 'highlight.js/lib/languages/rust';
import shell from 'highlight.js/lib/languages/shell';
import sql from 'highlight.js/lib/languages/sql';
import swift from 'highlight.js/lib/languages/swift';
import typescript from 'highlight.js/lib/languages/typescript';
import xml from 'highlight.js/lib/languages/xml';
import yaml from 'highlight.js/lib/languages/yaml';
import MarkdownIt from 'markdown-it';
import {
  computed,
  onBeforeUnmount,
  onMounted,
  shallowRef,
  useTemplateRef,
  watch,
  type ComputedRef,
} from 'vue';

export type MarkdownContentProps = {
  source: string;
};

const languages = {
  bash,
  c,
  cpp,
  csharp,
  css,
  diff,
  dockerfile,
  go,
  ini,
  java,
  javascript,
  json,
  kotlin,
  markdown: markdownLanguage,
  matlab,
  php,
  powershell,
  python,
  ruby,
  rust,
  shell,
  sql,
  swift,
  typescript,
  xml,
  yaml,
};

Object.entries(languages).forEach(([name, language]) => {
  highlighter.registerLanguage(name, language);
});

const languageAliases: Record<string, string> = {
  'c++': 'cpp',
  cc: 'cpp',
  console: 'shell',
  cs: 'csharp',
  docker: 'dockerfile',
  golang: 'go',
  h: 'c',
  hpp: 'cpp',
  html: 'xml',
  js: 'javascript',
  jsonc: 'json',
  jsx: 'javascript',
  kt: 'kotlin',
  md: 'markdown',
  patch: 'diff',
  ps1: 'powershell',
  py: 'python',
  rb: 'ruby',
  rs: 'rust',
  sh: 'bash',
  shell: 'bash',
  shellsession: 'shell',
  svg: 'xml',
  toml: 'ini',
  ts: 'typescript',
  tsx: 'typescript',
  vue: 'xml',
  yml: 'yaml',
  zsh: 'bash',
};

const languageLabels: Record<string, string> = {
  bash: 'Shell',
  c: 'C',
  cpp: 'C++',
  csharp: 'C#',
  css: 'CSS',
  diff: 'Diff',
  dockerfile: 'Dockerfile',
  go: 'Go',
  ini: 'INI / TOML',
  java: 'Java',
  javascript: 'JavaScript',
  json: 'JSON',
  kotlin: 'Kotlin',
  markdown: 'Markdown',
  matlab: 'MATLAB',
  mermaid: 'Mermaid',
  php: 'PHP',
  powershell: 'PowerShell',
  python: 'Python',
  ruby: 'Ruby',
  rust: 'Rust',
  shell: 'Shell',
  sql: 'SQL',
  swift: 'Swift',
  typescript: 'TypeScript',
  xml: 'HTML / XML',
  yaml: 'YAML',
};

const copyIcon =
  '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>';
const wrapIcon =
  '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m16 16-2 2 2 2"/><path d="M3 12h15a3 3 0 1 1 0 6h-4"/><path d="M3 18h7"/><path d="M3 6h18"/></svg>';

const diagramIcon =
  '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="6" height="6" rx="1"/><rect x="15" y="15" width="6" height="6" rx="1"/><path d="M6 9v3a3 3 0 0 0 3 3h6"/></svg>';

// Finished diagrams by source, so a re-rendered message shows them without a flash.
// null marks a source Mermaid could not draw.
const diagrams = new Map<string, string | null>();
const pendingDiagrams = new Map<string, Promise<string | null>>();
const diagramLimit = 60;
let diagramSequence = 0;

const markdown = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: true,
  typographer: false,
  highlight(source, language) {
    const normalized = normalizeLanguage(language);
    if (!normalized || !highlighter.getLanguage(normalized)) {
      return codeLines(escapeHtml(source));
    }
    return codeLines(
      highlighter.highlight(source, {
        language: normalized,
        ignoreIllegals: true,
      }).value,
    );
  },
});

markdown.use(katex, {
  delimiters: 'all',
  throwOnError: false,
  trust: false,
});

const defaultLinkOpen = markdown.renderer.rules.link_open;
markdown.renderer.rules.link_open = (tokens, index, options, env, renderer) => {
  tokens[index]?.attrSet('target', '_blank');
  tokens[index]?.attrSet('rel', 'noopener noreferrer');
  return defaultLinkOpen
    ? defaultLinkOpen(tokens, index, options, env, renderer)
    : renderer.renderToken(tokens, index, options);
};

const defaultFence = markdown.renderer.rules.fence;
markdown.renderer.rules.fence = (tokens, index, options, env, renderer) => {
  const token = tokens[index];
  const closed = !!token && fenceClosed(token);
  if (token && !closed) {
    // While streaming, the closing fence arrives a character at a time; its first
    // characters are not shown as a line of code.
    const partial = new RegExp(`(^|\\n)[ \\t]*\\${token.markup[0]}{1,2}$`);
    token.content = token.content.replace(partial, '$1');
  }
  const language = normalizeLanguage(token?.info || '');
  // The language name is also streamed; a half-typed one is not shown as a label.
  const typing = !closed && !token?.content;
  const label = (!typing && (languageLabels[language] || language)) || '代码';
  const fence = defaultFence
    ? defaultFence(tokens, index, options, env, renderer)
    : renderer.renderToken(tokens, index, options);
  const content = token?.content || '';
  const lines = content.replace(/\n$/, '').split('\n').length;
  if (language === 'mermaid') return mermaidBlock(token, closed, fence, lines);
  return [
    lines > 1
      ? `<div class="markdown-code-block markdown-code-block--numbered" style="--code-digits: ${String(lines).length}">`
      : '<div class="markdown-code-block">',
    '<div class="markdown-code-header">',
    `<span class="markdown-code-language">${escapeHtml(label)}</span>`,
    `<button type="button" data-wrap-code aria-pressed="false" aria-label="自动换行" title="自动换行">${wrapIcon}</button>`,
    `<button type="button" data-copy-code>${copyIcon}<span data-copy-label>复制</span></button>`,
    '</div>',
    fence,
    '</div>',
  ].join('');
};

export function useMarkdownContent(props: MarkdownContentProps): {
  blocks: ComputedRef<string[]>;
  copyCode: (event: MouseEvent) => Promise<void>;
} {
  // Streaming re-renders on every text delta. Blocks whose source did not change keep
  // their rendered HTML, so only the block still being written is rendered and patched.
  let rendered = new Map<string, string>();
  // Coalesce updates within one display frame without adding a cooldown after rendering.
  const shown = shallowRef(props.source);
  let frame: number | undefined;
  watch(
    () => props.source,
    () => {
      if (typeof requestAnimationFrame === 'undefined') {
        shown.value = props.source;
        return;
      }
      if (frame !== undefined) return;
      frame = requestAnimationFrame(() => {
        frame = undefined;
        shown.value = props.source;
      });
    },
  );
  onBeforeUnmount(() => {
    if (frame !== undefined) cancelAnimationFrame(frame);
  });
  const blocks = computed(() => {
    const next = new Map<string, string>();
    const result = renderMarkdownBlocks(shown.value, rendered, next);
    rendered = next;
    return result;
  });
  const content = useTemplateRef<HTMLElement>('content');
  const draw = (): void => {
    if (content.value) void renderDiagrams(content.value);
  };
  onMounted(draw);
  watch(blocks, draw, { flush: 'post' });
  return { blocks, copyCode: copyMarkdownCode };
}

// Draws every closed Mermaid block under root that has no diagram yet.
export async function renderDiagrams(root: HTMLElement): Promise<void> {
  const blocks = root.querySelectorAll<HTMLElement>(
    '[data-mermaid-ready]:not(.markdown-mermaid--rendered):not(.markdown-mermaid--failed)',
  );
  await Promise.all(
    [...blocks].map(async (block) => {
      const source = block.querySelector('code')?.textContent?.replace(/\n$/, '') || '';
      const svg = await diagram(source);
      const target = block.querySelector('[data-mermaid-diagram]');
      if (!block.isConnected || !target) return;
      if (svg === null) block.classList.add('markdown-mermaid--failed');
      else {
        target.innerHTML = svg;
        block.classList.add('markdown-mermaid--rendered');
      }
    }),
  );
}

function diagram(source: string): Promise<string | null> {
  const known = diagrams.get(source);
  if (known !== undefined) return Promise.resolve(known);
  let pending = pendingDiagrams.get(source);
  if (!pending) {
    pending = drawDiagram(source).then((svg) => {
      if (diagrams.size >= diagramLimit) diagrams.delete(diagrams.keys().next().value as string);
      diagrams.set(source, svg);
      pendingDiagrams.delete(source);
      return svg;
    });
    pendingDiagrams.set(source, pending);
  }
  return pending;
}

let mermaidLoader: Promise<typeof import('mermaid').default> | undefined;

// Diagram source is model output: strict mode disables click handlers, and labels may only
// carry text formatting, so a diagram cannot load remote resources or run script.
async function drawDiagram(source: string): Promise<string | null> {
  if (!source.trim()) return null;
  const id = `markdown-mermaid-${++diagramSequence}`;
  try {
    mermaidLoader ??= import('mermaid').then(({ default: mermaid }) => {
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: 'strict',
        theme: 'neutral',
        fontFamily: 'inherit',
        dompurifyConfig: {
          ALLOWED_TAGS: ['b', 'br', 'code', 'em', 'i', 's', 'small', 'strong', 'sub', 'sup', 'u'],
          ALLOWED_ATTR: [],
        },
      });
      return mermaid;
    });
    const mermaid = await mermaidLoader;
    if (!(await mermaid.parse(source, { suppressErrors: true }))) return null;
    const holder = document.createElement('div');
    holder.innerHTML = (await mermaid.render(id, source)).svg;
    // Diagram links open like other message links instead of replacing the chat.
    holder.querySelectorAll('a').forEach((link) => {
      link.setAttribute('target', '_blank');
      link.setAttribute('rel', 'noopener noreferrer');
    });
    return holder.innerHTML;
  } catch {
    return null;
  } finally {
    document.getElementById(id)?.remove();
    document.getElementById('d' + id)?.remove();
  }
}

export function renderMarkdown(source: string): string {
  return renderMarkdownBlocks(source).join('');
}

// Renders each top-level block separately. The whole source is parsed together, so
// constructs that span blocks, such as reference links, still resolve.
export function renderMarkdownBlocks(
  source: string,
  previous?: ReadonlyMap<string, string>,
  next?: Map<string, string>,
): string[] {
  const env: Parameters<typeof markdown.parse>[1] = {};
  const tokens = markdown.parse(source, env);
  const references = env.references ? JSON.stringify(env.references) : '';
  const lines = previous || next ? source.split('\n') : [];
  const blocks: string[] = [];
  let start = 0;
  tokens.forEach((token, index) => {
    if (token.level !== 0 || token.nesting > 0) return;
    const group = tokens.slice(start, index + 1);
    const map = tokens[start]?.map;
    start = index + 1;
    const key = map ? `${references}\n${lines.slice(map[0], map[1]).join('\n')}` : undefined;
    const html =
      (key !== undefined && previous?.get(key)) ||
      markdown.renderer.render(group, markdown.options, env);
    if (key !== undefined) next?.set(key, html);
    blocks.push(html);
  });
  return blocks;
}

export async function copyMarkdownCode(event: MouseEvent): Promise<void> {
  const target = event.target;
  if (!(target instanceof Element)) {
    return;
  }
  const toggle = target.closest<HTMLButtonElement>('[data-mermaid-toggle]');
  if (toggle) {
    const source = toggle
      .closest('.markdown-mermaid')
      ?.classList.toggle('markdown-mermaid--source');
    toggle.setAttribute('aria-pressed', String(!source));
    return;
  }
  const wrap = target.closest<HTMLButtonElement>('[data-wrap-code]');
  if (wrap) {
    const wrapped = wrap
      .closest('.markdown-code-block')
      ?.classList.toggle('markdown-code-block--wrapped');
    wrap.setAttribute('aria-pressed', String(!!wrapped));
    return;
  }
  const button = target.closest<HTMLButtonElement>('[data-copy-code]');
  const code = button?.closest('.markdown-code-block')?.querySelector('code');
  if (!button || !code?.textContent) {
    return;
  }
  try {
    await navigator.clipboard.writeText(code.textContent.replace(/\n$/, ''));
    showCopyResult(button, '已复制');
  } catch {
    showCopyResult(button, '复制失败');
  }
}

function normalizeLanguage(value: string): string {
  const language = value.trim().split(/\s+/, 1)[0]?.toLowerCase() || '';
  return languageAliases[language] || language;
}

function fenceClosed(token: { content: string; map: [number, number] | null }): boolean {
  const content = token.content;
  const contentLines = content ? content.replace(/\n$/, '').split('\n').length : 0;
  return !!token.map && token.map[1] - token.map[0] === contentLines + 2;
}

function mermaidBlock(
  token: { content: string } | undefined,
  closed: boolean,
  fence: string,
  lines: number,
): string {
  const content = token?.content || '';
  const svg = closed ? diagrams.get(content.replace(/\n$/, '')) : undefined;
  const state = svg
    ? ' markdown-mermaid--rendered'
    : svg === null
      ? ' markdown-mermaid--failed'
      : '';
  return [
    `<div class="markdown-code-block markdown-mermaid${lines > 1 ? ' markdown-code-block--numbered' : ''}${state}" style="--code-digits: ${String(lines).length}"${closed ? ' data-mermaid-ready' : ''}>`,
    '<div class="markdown-code-header">',
    '<span class="markdown-code-language">Mermaid</span>',
    '<span class="markdown-mermaid-error">图表语法有误，显示源码</span>',
    `<button type="button" data-mermaid-toggle aria-pressed="true" aria-label="显示图表" title="图表 / 源码">${diagramIcon}</button>`,
    `<button type="button" data-wrap-code aria-pressed="false" aria-label="自动换行" title="自动换行">${wrapIcon}</button>`,
    `<button type="button" data-copy-code>${copyIcon}<span data-copy-label>复制</span></button>`,
    '</div>',
    `<div class="markdown-mermaid-diagram" data-mermaid-diagram>${svg || ''}</div>`,
    fence,
    '</div>',
  ].join('');
}

// Each line gets its own element so numbering and wrapping stay aligned;
// highlight spans that cross a line break are closed and reopened.
function codeLines(html: string): string {
  const open: string[] = [];
  return html
    .replace(/\n$/, '')
    .split('\n')
    .map((line) => {
      const prefix = open.join('');
      for (const [tag] of line.matchAll(/<span[^>]*>|<\/span>/g)) {
        if (tag === '</span>') open.pop();
        else open.push(tag);
      }
      return `<span class="code-line">${prefix}${line}\n${'</span>'.repeat(open.length)}</span>`;
    })
    .join('');
}

function showCopyResult(button: HTMLButtonElement, label: string): void {
  const text = button.querySelector('[data-copy-label]');
  if (!text) return;
  text.textContent = label;
  window.setTimeout(() => {
    text.textContent = '复制';
  }, 1600);
}

function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}
