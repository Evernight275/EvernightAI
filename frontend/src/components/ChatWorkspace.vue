<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import css from 'highlight.js/lib/languages/css'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import markdown from 'highlight.js/lib/languages/markdown'
import python from 'highlight.js/lib/languages/python'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import katex from 'katex'
import type { Content, Session } from '../api'
import { shortId } from '../format'
import Icon from './Icon.vue'
import { useToast } from '../composables/useToast'

type ModelOption = {
  value: string
  label: string
}

type MathPlaceholder = {
  placeholder: string
  html: string
  displayMode: boolean
}

const toast = useToast()

const props = defineProps<{
  sessions: Session[]
  modelOptions: ModelOption[]
  selectedSessionId: string | null
  messages: Array<Content & {
    outgoing?: boolean
    text: string
    pending?: boolean
    contextIndex?: number
  }>
  title: string
  loading: boolean
  sending: boolean
  creatingSession: boolean
  disabled: boolean
  error: string | null
}>()

const model = defineModel<string>({ required: true })
const modelSelection = defineModel<string>('modelSelection', { required: true })
const timeoutSeconds = defineModel<number>('timeoutSeconds', { required: true })
const streamEnabled = defineModel<boolean>('streamEnabled', { required: true })
const agentEnabled = defineModel<boolean>('agentEnabled', { required: true })
const modelPickerOpen = ref(false)
const settingsOpen = ref(false)
const chatThread = ref<HTMLElement | null>(null)
const chatInput = ref<HTMLTextAreaElement | null>(null)
const selectedModelLabel = computed(() => (
  props.modelOptions.find((option) => option.value === modelSelection.value)?.label
  || props.modelOptions[0]?.label
  || '选择模型'
))
const emit = defineEmits<{
  select: [session: Session]
  send: [text: string]
  retryMessage: [message: Content & { outgoing?: boolean; text: string; pending?: boolean; contextIndex?: number }]
  createSession: []
  renameSession: [session: Session]
  deleteSession: [session: Session]
}>()

const copiedMessageIndex = ref<number | null>(null)
const copiedCodeBlock = ref<string | null>(null)

function copyToClipboard(text: string, identifier: string | number) {
  navigator.clipboard.writeText(text).then(() => {
    if (typeof identifier === 'number') {
      copiedMessageIndex.value = identifier
      setTimeout(() => {
        copiedMessageIndex.value = null
      }, 2000)
    } else {
      copiedCodeBlock.value = identifier
      setTimeout(() => {
        copiedCodeBlock.value = null
      }, 2000)
    }
    toast.success('已复制到剪贴板')
  }).catch((error) => {
    console.error('复制失败:', error)
    toast.error('复制失败，请重试')
  })
}

function copyMessage(message: Content & { text: string }, index: number) {
  copyToClipboard(message.text, index)
}

function addCodeCopyButtons() {
  nextTick(() => {
    const thread = chatThread.value
    if (!thread) return

    const codeBlocks = thread.querySelectorAll('pre.hljs')
    codeBlocks.forEach((block, index) => {
      const existingButton = block.querySelector('.code-copy-button')
      if (existingButton) return

      const button = document.createElement('button')
      button.className = 'code-copy-button'
      button.type = 'button'
      button.title = '复制代码'
      button.innerHTML = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>'

      const codeElement = block.querySelector('code')
      if (codeElement) {
        const code = codeElement.textContent || ''
        button.addEventListener('click', () => {
          copyToClipboard(code, `code-${index}`)
          button.classList.add('copied')
          button.innerHTML = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>'
          setTimeout(() => {
            button.classList.remove('copied')
            button.innerHTML = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>'
          }, 2000)
        })
      }

      block.appendChild(button)
    })
  })
}

hljs.registerLanguage('bash', bash)
hljs.registerLanguage('css', css)
hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('json', json)
hljs.registerLanguage('markdown', markdown)
hljs.registerLanguage('python', python)
hljs.registerLanguage('typescript', typescript)
hljs.registerLanguage('xml', xml)

const languageAliases: Record<string, string> = {
  html: 'xml',
  js: 'javascript',
  jsx: 'javascript',
  md: 'markdown',
  py: 'python',
  sh: 'bash',
  shell: 'bash',
  ts: 'typescript',
  tsx: 'typescript',
  vue: 'xml',
  zsh: 'bash',
}

const markdownRenderer = new MarkdownIt({
  breaks: true,
  highlight(code, language) {
    const normalizedLanguage = normalizeHighlightLanguage(language)
    if (normalizedLanguage) {
      const highlighted = hljs.highlight(code, {
        language: normalizedLanguage,
        ignoreIllegals: true,
      }).value
      return codeBlockHtml(highlighted, normalizedLanguage)
    }

    const highlighted = hljs.highlightAuto(code).value
    return codeBlockHtml(highlighted, 'text')
  },
  html: false,
  linkify: true,
})

const defaultRenderLinkOpen = markdownRenderer.renderer.rules.link_open
markdownRenderer.renderer.rules.link_open = (tokens, index, options, env, self) => {
  const token = tokens[index]
  token.attrSet('target', '_blank')
  token.attrSet('rel', 'noreferrer')
  return defaultRenderLinkOpen
    ? defaultRenderLinkOpen(tokens, index, options, env, self)
    : self.renderToken(tokens, index, options)
}

function submit() {
  const text = model.value.trim()
  if (text !== '') {
    modelPickerOpen.value = false
    emit('send', text)
  }
}

function toggleModelPicker() {
  if (props.sending || props.modelOptions.length === 0) {
    return
  }

  modelPickerOpen.value = !modelPickerOpen.value
}

function selectModel(value: string) {
  modelSelection.value = value
  modelPickerOpen.value = false
}

function resizeChatInput() {
  const input = chatInput.value
  if (!input) {
    return
  }

  input.style.height = 'auto'
  input.style.height = `${input.scrollHeight}px`
}

async function scrollThreadToBottom() {
  await nextTick()
  const thread = chatThread.value
  if (!thread) {
    return
  }

  thread.scrollTop = thread.scrollHeight
}

function toggleSettings() {
  if (props.sending) {
    return
  }

  settingsOpen.value = !settingsOpen.value
}

function renderMarkdown(text: string): string {
  const normalized = text.replace(/\r\n?/g, '\n').trim()
  if (normalized === '') {
    return '<p>无文本内容</p>'
  }

  const math = extractMathPlaceholders(normalized)
  return restoreMathPlaceholders(markdownRenderer.render(math.markdown), math.placeholders)
}

function codeBlockHtml(highlightedCode: string, language: string): string {
  return `<pre class="hljs" data-language="${language}"><code class="language-${language}">${highlightedCode}</code></pre>`
}

function extractMathPlaceholders(text: string): {
  markdown: string
  placeholders: MathPlaceholder[]
} {
  const placeholders: MathPlaceholder[] = []
  const markdown = splitMarkdownCodeFences(text)
    .map((segment) => (
      segment.isCode ? segment.text : extractMathFromText(segment.text, placeholders)
    ))
    .join('')

  return { markdown, placeholders }
}

function splitMarkdownCodeFences(text: string): Array<{ text: string; isCode: boolean }> {
  const segments: Array<{ text: string; isCode: boolean }> = []
  const fencePattern = /(^|\n)(```|~~~)[^\n]*(?:\n[\s\S]*?\n\2[^\n]*(?=\n|$)|[\s\S]*$)/g
  let cursor = 0
  let match: RegExpExecArray | null

  while ((match = fencePattern.exec(text)) !== null) {
    const start = match.index + match[1].length
    if (start > cursor) {
      segments.push({ text: text.slice(cursor, start), isCode: false })
    }
    segments.push({ text: text.slice(start, fencePattern.lastIndex), isCode: true })
    cursor = fencePattern.lastIndex
  }

  if (cursor < text.length) {
    segments.push({ text: text.slice(cursor), isCode: false })
  }

  return segments
}

function extractMathFromText(text: string, placeholders: MathPlaceholder[]): string {
  let output = ''
  let index = 0

  while (index < text.length) {
    const blockBracket = readDelimitedFormula(text, index, '\\[', '\\]')
    if (blockBracket !== null) {
      output += mathPlaceholder(blockBracket.formula, true, placeholders)
      index = blockBracket.end
      continue
    }

    const inlineParen = readDelimitedFormula(text, index, '\\(', '\\)')
    if (inlineParen !== null) {
      output += mathPlaceholder(inlineParen.formula, false, placeholders)
      index = inlineParen.end
      continue
    }

    const blockDollar = readDollarBlockFormula(text, index)
    if (blockDollar !== null) {
      output += mathPlaceholder(blockDollar.formula, true, placeholders)
      index = blockDollar.end
      continue
    }

    const inlineDollar = readDollarInlineFormula(text, index)
    if (inlineDollar !== null) {
      output += mathPlaceholder(inlineDollar.formula, false, placeholders)
      index = inlineDollar.end
      continue
    }

    output += text[index]
    index += 1
  }

  return output
}

function readDelimitedFormula(
  text: string,
  index: number,
  opener: string,
  closer: string,
): { formula: string; end: number } | null {
  if (!text.startsWith(opener, index)) {
    return null
  }

  const closeIndex = findUnescaped(text, closer, index + opener.length)
  if (closeIndex === -1) {
    return null
  }

  return {
    formula: text.slice(index + opener.length, closeIndex),
    end: closeIndex + closer.length,
  }
}

function readDollarBlockFormula(
  text: string,
  index: number,
): { formula: string; end: number } | null {
  if (!text.startsWith('$$', index) || isEscaped(text, index)) {
    return null
  }

  const closeIndex = findUnescaped(text, '$$', index + 2)
  if (closeIndex === -1) {
    return null
  }

  return {
    formula: text.slice(index + 2, closeIndex),
    end: closeIndex + 2,
  }
}

function readDollarInlineFormula(
  text: string,
  index: number,
): { formula: string; end: number } | null {
  if (text[index] !== '$' || text[index + 1] === '$' || isEscaped(text, index)) {
    return null
  }

  const next = text[index + 1]
  if (next === undefined || /\s/.test(next)) {
    return null
  }

  let closeIndex = text.indexOf('$', index + 1)
  while (closeIndex !== -1) {
    const previous = text[closeIndex - 1]
    const following = text[closeIndex + 1]
    if (
      !isEscaped(text, closeIndex)
      && previous !== undefined
      && !/\s/.test(previous)
      && (following === undefined || !/\d/.test(following))
    ) {
      return {
        formula: text.slice(index + 1, closeIndex),
        end: closeIndex + 1,
      }
    }
    closeIndex = text.indexOf('$', closeIndex + 1)
  }

  return null
}

function findUnescaped(text: string, needle: string, start: number): number {
  let index = text.indexOf(needle, start)
  while (index !== -1) {
    if (!isEscaped(text, index)) {
      return index
    }
    index = text.indexOf(needle, index + needle.length)
  }

  return -1
}

function isEscaped(text: string, index: number): boolean {
  let slashCount = 0
  for (let cursor = index - 1; cursor >= 0 && text[cursor] === '\\'; cursor -= 1) {
    slashCount += 1
  }

  return slashCount % 2 === 1
}

function mathPlaceholder(
  formula: string,
  displayMode: boolean,
  placeholders: MathPlaceholder[],
): string {
  const placeholder = `@@EVERNIGHT_MATH_${placeholders.length}@@`
  const mathHtml = katex.renderToString(formula.trim(), {
    displayMode,
    errorColor: '#b3261e',
    throwOnError: false,
  })

  placeholders.push({
    placeholder,
    html: displayMode
      ? `<div class="math-block">${mathHtml}</div>`
      : `<span class="math-inline">${mathHtml}</span>`,
    displayMode,
  })

  return displayMode ? `\n\n${placeholder}\n\n` : placeholder
}

function restoreMathPlaceholders(html: string, placeholders: MathPlaceholder[]): string {
  let restored = html
  placeholders.forEach((item) => {
    if (item.displayMode) {
      restored = restored.replaceAll(`<p>${item.placeholder}</p>`, item.html)
    }
    restored = restored.replaceAll(item.placeholder, item.html)
  })

  return restored
}

function normalizeHighlightLanguage(language: string): string | null {
  const cleanLanguage = language.trim().toLowerCase()
  if (cleanLanguage === '') {
    return null
  }

  const normalizedLanguage = languageAliases[cleanLanguage] || cleanLanguage
  return hljs.getLanguage(normalizedLanguage) ? normalizedLanguage : null
}

watch(model, async () => {
  await nextTick()
  resizeChatInput()
})

watch(
  () => props.messages.map((message) => `${message.role}:${message.text}`).join('\n'),
  () => {
    void scrollThreadToBottom()
    addCodeCopyButtons()
  },
  { flush: 'post' },
)

onMounted(() => {
  resizeChatInput()
  void scrollThreadToBottom()
  addCodeCopyButtons()
})
</script>

<template>
  <section class="chat-workspace" aria-label="聊天工作区">
    <aside class="chat-rail">
      <div class="chat-rail-head">
        <strong>会话</strong>
        <button class="button icon-button" type="button" :disabled="creatingSession" @click="emit('createSession')">
          <Icon name="message-square-plus" />
        </button>
      </div>
      <div class="chat-session-list">
        <div
          v-for="session in sessions"
          :key="session.session_id"
          class="chat-session-button"
          :class="{ 'is-selected': session.session_id === selectedSessionId }"
          @click="emit('select', session)"
        >
          <button class="chat-session-main" type="button">
            <span>{{ session.title || shortId(session.session_id) }}</span>
          </button>
          <div class="chat-session-actions">
            <button
              class="session-action-button"
              type="button"
              title="重命名"
              aria-label="重命名会话"
              @click.stop="emit('renameSession', session)"
            >
              <Icon name="pencil" />
            </button>
            <button
              class="session-action-button danger"
              type="button"
              title="删除"
              aria-label="删除会话"
              @click.stop="emit('deleteSession', session)"
            >
              <Icon name="trash-2" />
            </button>
          </div>
        </div>
        <div v-if="sessions.length === 0" class="chat-rail-empty">
          暂无会话
        </div>
      </div>
      <div class="chat-settings" :class="{ 'is-open': settingsOpen }">
        <button
          class="settings-trigger"
          type="button"
          :disabled="sending"
          :aria-expanded="settingsOpen"
          @click="toggleSettings"
        >
          <Icon name="settings" />
          <span>设置</span>
        </button>
        <Transition name="settings-panel">
          <div v-if="settingsOpen" class="settings-panel">
            <label class="setting-row">
              <span>Timeout</span>
              <input
                v-model.number="timeoutSeconds"
                min="1"
                max="600"
                step="1"
                type="number"
                :disabled="sending"
              />
            </label>
            <label class="setting-toggle">
              <span>流式</span>
              <input v-model="streamEnabled" type="checkbox" :disabled="sending" />
            </label>
            <label class="setting-toggle">
              <span>Agent 路线</span>
              <input v-model="agentEnabled" type="checkbox" :disabled="sending" />
            </label>
          </div>
        </Transition>
      </div>
    </aside>

    <div class="chat-main">
      <header class="chat-main-head">
        <div>
          <h2>{{ title }}</h2>
          <p>{{ selectedSessionId ? '当前上下文会被服务端持久化' : '新建或选择一个会话' }}</p>
        </div>
      </header>

      <div ref="chatThread" class="chat-thread">
        <div v-if="loading && messages.length === 0" class="chat-thread-message system">
          <div class="message-markdown" v-html="renderMarkdown('正在加载上下文...')"></div>
        </div>
        <div
          v-else
          v-for="(message, index) in messages"
          :key="`${message.role}-${index}`"
          class="chat-thread-message"
          :class="{
            assistant: message.role === 'assistant',
            user: message.role === 'user',
            pending: message.pending,
          }"
        >
          <div class="message-markdown" v-html="renderMarkdown(message.text || '无文本内容')"></div>
          <div class="message-actions">
            <button
              v-if="message.role === 'assistant' && !message.pending"
              class="message-action-button"
              type="button"
              title="重试"
              aria-label="重试回答"
              :disabled="sending || message.contextIndex === undefined"
              @click="emit('retryMessage', message)"
            >
              <Icon name="rotate-ccw" />
            </button>
            <button
              class="message-action-button"
              type="button"
              :title="copiedMessageIndex === index ? '已复制' : '复制消息'"
              :aria-label="copiedMessageIndex === index ? '已复制' : '复制消息'"
              @click="copyMessage(message, index)"
            >
              <Icon :name="copiedMessageIndex === index ? 'check' : 'copy'" />
            </button>
          </div>
        </div>
        <div v-if="loading && messages.length > 0" class="chat-thread-sync">
          正在同步上下文...
        </div>
      </div>

      <form class="chat-composer" @submit.prevent="submit">
        <div class="chat-input-shell">
          <textarea
            ref="chatInput"
            v-model="model"
            rows="1"
            placeholder="给当前会话发送消息"
            :disabled="disabled || sending"
            @focus="modelPickerOpen = false"
            @input="resizeChatInput"
            @keydown.enter.exact.prevent="submit"
          ></textarea>
          <div class="chat-input-actions">
            <div class="model-picker" :class="{ 'is-open': modelPickerOpen }">
              <button
                class="model-picker-trigger"
                type="button"
                :disabled="sending || modelOptions.length === 0"
                :aria-expanded="modelPickerOpen"
                aria-haspopup="listbox"
                @click="toggleModelPicker"
              >
                <span>{{ selectedModelLabel }}</span>
                <Icon name="chevron-down" />
              </button>
              <Transition name="model-menu">
                <div v-if="modelPickerOpen" class="model-picker-menu" role="listbox">
                  <button
                  v-for="option in modelOptions"
                  :key="option.value"
                    class="model-picker-option"
                    :class="{ 'is-selected': option.value === modelSelection }"
                    type="button"
                    role="option"
                    :aria-selected="option.value === modelSelection"
                    @click="selectModel(option.value)"
                >
                  {{ option.label }}
                  </button>
                </div>
              </Transition>
            </div>
            <button
              class="chat-send-button"
              type="submit"
              :disabled="disabled || sending || model.trim() === ''"
              :title="sending ? 'Agent 运行中' : '发送'"
              :aria-label="sending ? 'Agent 运行中' : '发送'"
            >
              <Icon name="send" />
            </button>
          </div>
        </div>
        <span class="chat-composer-hint">{{ error || 'Enter 发送，默认走 Agent' }}</span>
      </form>
    </div>
  </section>
</template>
