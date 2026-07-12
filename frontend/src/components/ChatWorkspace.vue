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
import type {
  Content,
  ContentPart,
  ProviderModelCapability,
  Session,
  ToolApprovalRequest,
} from '../api'
import { shortId } from '../format'
import Icon from './Icon.vue'
import { useToast } from '../composables/useToast'

type ModelOption = {
  value: string
  label: string
  capabilities: ProviderModelCapability[]
}

type MathPlaceholder = {
  placeholder: string
  html: string
  displayMode: boolean
}

type JsonObject = Record<string, unknown>
type ChatMessage = Content & {
  outgoing?: boolean
  text: string
  pending?: boolean
  contextIndex?: number
  toolActivityMessages?: ChatMessage[]
}

const toast = useToast()

const props = defineProps<{
  sessions: Session[]
  modelOptions: ModelOption[]
  selectedSessionId: string | null
  messages: ChatMessage[]
  title: string
  loading: boolean
  sending: boolean
  approvingApproval: boolean
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
const imageInput = ref<HTMLInputElement | null>(null)
const selectedImages = ref<ContentPart[]>([])
const MAX_IMAGE_COUNT = 4
const MAX_IMAGE_BYTES = 5 * 1024 * 1024
const ACCEPTED_IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp', 'image/gif'])
const selectedModelOption = computed(() => (
  props.modelOptions.find((option) => option.value === modelSelection.value)
  || props.modelOptions[0]
))
const selectedModelLabel = computed(() => (
  selectedModelOption.value?.label
  || props.modelOptions[0]?.label
  || '选择模型'
))
const supportsImageInput = computed(() => (
  selectedModelOption.value?.capabilities.includes('image_recognition') === true
))
const sendButtonLabel = computed(() => {
  if (props.sending) {
    return 'Agent 运行中'
  }
  if (props.disabled) {
    return '请先选择可用模型'
  }
  if (selectedImages.value.length > 0 && !supportsImageInput.value) {
    return '当前模型不支持图片识别'
  }
  if (!canSubmit.value) {
    return '输入消息后发送'
  }

  return '发送'
})
const emit = defineEmits<{
  select: [session: Session]
  send: [message: { text: string; images: ContentPart[] }]
  retryMessage: [message: ChatMessage]
  approveToolApproval: [message: ChatMessage]
  denyToolApproval: [message: ChatMessage]
  createSession: []
  renameSession: [session: Session]
  deleteSession: [session: Session]
}>()
const canSubmit = computed(() => (
  (model.value.trim() !== '' || selectedImages.value.length > 0)
  && (selectedImages.value.length === 0 || supportsImageInput.value)
))

const copiedMessageIndex = ref<number | null>(null)
const copiedCodeBlock = ref<string | null>(null)
let threadRefreshTimer: number | undefined

const groupedMessages = computed<ChatMessage[]>(() => groupToolActivityMessages(props.messages))
const primaryApprovalMessage = computed<ChatMessage | null>(() => (
  groupedMessages.value.find((message) => isToolApprovalMessage(message)) || null
))
const displayMessages = computed<ChatMessage[]>(() => (
  groupedMessages.value.filter((message) => !isToolApprovalMessage(message))
))

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
      button.setAttribute('aria-label', '复制代码')
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
  if (canSubmit.value) {
    modelPickerOpen.value = false
    emit('send', { text, images: [...selectedImages.value] })
    selectedImages.value = []
  }
}

function openImagePicker() {
  if (!supportsImageInput.value) {
    toast.warning('当前模型未声明图片识别能力')
    return
  }
  imageInput.value?.click()
}

async function selectImages(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''

  for (const file of files) {
    if (selectedImages.value.length >= MAX_IMAGE_COUNT) {
      toast.warning(`每条消息最多添加 ${MAX_IMAGE_COUNT} 张图片`)
      break
    }
    if (!ACCEPTED_IMAGE_TYPES.has(file.type)) {
      toast.error(`不支持的图片格式：${file.name}`)
      continue
    }
    if (file.size > MAX_IMAGE_BYTES) {
      toast.error(`图片超过 5 MiB：${file.name}`)
      continue
    }

    try {
      selectedImages.value.push({
        type: 'image',
        data: await readImageData(file),
        mime_type: file.type,
        metadata: { name: file.name, size: file.size },
      })
    } catch (error) {
      toast.error(error instanceof Error ? error.message : `无法读取图片：${file.name}`)
    }
  }
}

function readImageData(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = typeof reader.result === 'string' ? reader.result : ''
      const separator = result.indexOf(',')
      if (separator === -1) {
        reject(new Error(`无法读取图片：${file.name}`))
        return
      }
      resolve(result.slice(separator + 1))
    }
    reader.onerror = () => reject(reader.error || new Error(`无法读取图片：${file.name}`))
    reader.readAsDataURL(file)
  })
}

function removeImage(index: number) {
  selectedImages.value.splice(index, 1)
}

function imageSource(part: ContentPart): string | null {
  if (part.url) {
    return part.url
  }
  if (!part.data) {
    return null
  }
  if (part.data.startsWith('data:')) {
    return part.data
  }
  return part.mime_type ? `data:${part.mime_type};base64,${part.data}` : null
}

function messageImages(message: Content): ContentPart[] {
  return (message.content || []).filter(
    (part) => part.type === 'image' && imageSource(part) !== null,
  )
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

function closePopovers() {
  modelPickerOpen.value = false
  settingsOpen.value = false
}

function handleWorkspaceClick(event: MouseEvent) {
  const target = event.target
  if (!(target instanceof Element)) {
    return
  }

  if (!target.closest('.model-picker')) {
    modelPickerOpen.value = false
  }
  if (!target.closest('.chat-settings')) {
    settingsOpen.value = false
  }
}

function renderMarkdown(text: string): string {
  const normalized = text.replace(/\r\n?/g, '\n').trim()
  if (normalized === '') {
    return '<p>无文本内容</p>'
  }

  const math = extractMathPlaceholders(normalized)
  return restoreMathPlaceholders(markdownRenderer.render(math.markdown), math.placeholders)
}

function isToolResultMessage(message: Content): boolean {
  return message.role === 'tool' || Boolean(message.tool_call_id)
}

function isToolCallMessage(message: Content): boolean {
  return Array.isArray(message.tool_calls) && message.tool_calls.length > 0
}

function isToolActivityMessage(message: ChatMessage): boolean {
  return Array.isArray(message.toolActivityMessages)
}

function isToolApprovalMessage(message: ChatMessage): boolean {
  return Boolean(approvalRequest(message))
}

function approvalRequest(message: ChatMessage): ToolApprovalRequest | null {
  const request = message.metadata?.approval_request
  if (
    typeof request === 'object'
    && request !== null
    && typeof (request as ToolApprovalRequest).approval_id === 'string'
    && typeof (request as ToolApprovalRequest).tool_call_id === 'string'
    && typeof (request as ToolApprovalRequest).tool_name === 'string'
  ) {
    return request as ToolApprovalRequest
  }

  return null
}

function approvalPermissions(message: ChatMessage): string {
  const request = approvalRequest(message)
  return request?.permissions?.join(' / ') || '无特殊权限'
}

function approvalDetail(message: ChatMessage): string {
  const request = approvalRequest(message)
  return request ? formatJson(request) : '{}'
}

function approvalToolName(message: ChatMessage | null): string {
  return approvalRequestFromNullable(message)?.tool_name || '工具'
}

function approvalSafetySummary(message: ChatMessage | null): string {
  const request = approvalRequestFromNullable(message)
  if (!request) {
    return ''
  }

  const permissions = request.permissions?.join(' / ') || '无特殊权限'
  return `${request.safety_level || 'safe'} · ${permissions}`
}

function approvalRequestFromNullable(message: ChatMessage | null): ToolApprovalRequest | null {
  return message ? approvalRequest(message) : null
}

function groupToolActivityMessages(messages: ChatMessage[]): ChatMessage[] {
  const grouped: ChatMessage[] = []
  let index = 0

  while (index < messages.length) {
    const message = messages[index]
    if (!isToolTimelineMessage(message)) {
      grouped.push(message)
      index += 1
      continue
    }

    const toolMessages: ChatMessage[] = []
    while (index < messages.length && isToolTimelineMessage(messages[index])) {
      toolMessages.push(messages[index])
      index += 1
    }

    if (toolMessages.length === 1) {
      grouped.push(toolMessages[0])
      continue
    }

    grouped.push({
      role: 'system',
      content: [{ type: 'text', text: toolActivitySummary(toolMessages) }],
      text: toolActivitySummary(toolMessages),
      pending: toolMessages.some((item) => item.pending),
      toolActivityMessages: toolMessages,
    })
  }

  return grouped
}

function isToolTimelineMessage(message: ChatMessage): boolean {
  return !isToolApprovalMessage(message) && (isToolResultMessage(message) || isToolCallMessage(message))
}

function toolActivitySummary(messages: ChatMessage[]): string {
  const callCount = messages.filter((message) => isToolCallMessage(message)).length
  const resultCount = messages.filter((message) => isToolResultMessage(message)).length
  const pendingCount = messages.filter((message) => message.pending).length
  const parts = [
    callCount > 0 ? `${callCount} 个调用` : '',
    resultCount > 0 ? `${resultCount} 个结果` : '',
    pendingCount > 0 ? `${pendingCount} 个进行中` : '',
  ].filter(Boolean)

  return parts.join(' · ') || `${messages.length} 条工具事件`
}

function toolActivityNames(messages: ChatMessage[]): string {
  const names = messages.flatMap((message) => (
    (message.tool_calls || [])
      .map((call) => {
        const name = call.tool_call?.name
        return typeof name === 'string' && name ? name : '未知工具'
      })
  ))

  return names.length > 0 ? names.slice(0, 5).join(' / ') : '工具活动'
}

function toolActivityItems(message: ChatMessage): ChatMessage[] {
  return message.toolActivityMessages || []
}

function toolActivitySummaryForMessage(message: ChatMessage): string {
  return toolActivitySummary(toolActivityItems(message))
}

function toolActivityNamesForMessage(message: ChatMessage): string {
  return toolActivityNames(toolActivityItems(message))
}

function toolResultTitle(message: Content & { text: string }): string {
  const payload = parseJsonObject(message.text)
  const result = objectField(payload, 'tool_call_result') || payload
  const path = stringField(result, 'path')
  if (path) {
    return `工具结果 · ${path}`
  }

  return `工具结果 · ${shortId(message.tool_call_id || stringField(payload, 'tool_call_id') || '')}`
}

function toolResultSummary(message: Content & { text: string }): string {
  const payload = parseJsonObject(message.text)
  const result = objectField(payload, 'tool_call_result') || payload
  const path = stringField(result, 'path')
  const content = stringField(result, 'content')
  const truncated = booleanField(result, 'truncated')
  if (path && content !== null) {
    const suffix = truncated ? ' · 已截断' : ''
    return `文件读取 · ${content.length} 字符${suffix}`
  }

  const keys = Object.keys(result)
  if (keys.length > 0) {
    return `返回字段：${keys.slice(0, 4).join(' / ')}${keys.length > 4 ? ' ...' : ''}`
  }

  return compactText(message.text || '空结果')
}

function toolResultDetail(message: Content & { text: string }): string {
  const parsed = parseJsonObject(message.text)
  return parsed === emptyObject ? message.text : formatJson(parsed)
}

function toolCallTitle(message: Content): string {
  const count = message.tool_calls?.length || 0
  return `工具调用 · ${count} 个`
}

function toolCallSummary(message: Content): string {
  const calls = message.tool_calls || []
  const names = calls
    .map((call) => {
      const name = call.tool_call?.name
      return typeof name === 'string' && name ? name : '未知工具'
    })
  return names.join(' / ') || '等待工具返回'
}

function toolCallDetail(message: Content): string {
  return formatJson(message.tool_calls || [])
}

function compactText(value: string): string {
  const compact = value.replace(/\s+/g, ' ').trim()
  return compact.length > 120 ? `${compact.slice(0, 119)}...` : compact
}

function formatJson(value: unknown): string {
  if (typeof value === 'string') {
    return value
  }

  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

const emptyObject: JsonObject = {}

function parseJsonObject(value: string): JsonObject {
  try {
    const parsed = JSON.parse(value)
    return isJsonObject(parsed) ? parsed : emptyObject
  } catch {
    return emptyObject
  }
}

function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function objectField(value: JsonObject, key: string): JsonObject | null {
  const field = value[key]
  return isJsonObject(field) ? field : null
}

function stringField(value: JsonObject, key: string): string | null {
  const field = value[key]
  return typeof field === 'string' && field !== '' ? field : null
}

function booleanField(value: JsonObject, key: string): boolean {
  return value[key] === true
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
    scheduleThreadRefresh()
  },
  { flush: 'post' },
)

function scheduleThreadRefresh() {
  if (threadRefreshTimer !== undefined) {
    return
  }

  threadRefreshTimer = window.setTimeout(() => {
    threadRefreshTimer = undefined
    void scrollThreadToBottom()
    addCodeCopyButtons()
  }, 80)
}

onMounted(() => {
  resizeChatInput()
  void scrollThreadToBottom()
  addCodeCopyButtons()
})
</script>

<template>
  <section
    class="chat-workspace"
    aria-label="聊天工作区"
    @click="handleWorkspaceClick"
    @keydown.esc="closePopovers"
  >
    <aside class="chat-rail">
      <div class="chat-rail-head">
        <strong>会话</strong>
        <button
          class="button icon-button"
          type="button"
          :disabled="creatingSession"
          title="新建会话"
          aria-label="新建会话"
          @click="emit('createSession')"
        >
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
          <button
            class="chat-session-main"
            type="button"
            :aria-pressed="session.session_id === selectedSessionId"
          >
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
          aria-controls="chat-settings-panel"
          @click="toggleSettings"
        >
          <Icon name="settings" />
          <span>设置</span>
          <Icon name="chevron-down" class="settings-chevron" />
        </button>
        <Transition name="settings-panel">
          <div v-if="settingsOpen" id="chat-settings-panel" class="settings-panel">
            <label class="setting-row">
              <span>超时（秒）</span>
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
              <input v-model="streamEnabled" type="checkbox" role="switch" :disabled="sending" />
            </label>
            <label class="setting-toggle">
              <span>Agent 路线</span>
              <input v-model="agentEnabled" type="checkbox" role="switch" :disabled="sending" />
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
        <div v-if="loading && messages.length === 0" class="chat-thread-message system" role="status">
          <div class="message-markdown" v-html="renderMarkdown('正在加载上下文...')"></div>
        </div>
        <div
          v-else
          v-for="(message, index) in displayMessages"
          :key="`${message.role}-${index}`"
          class="chat-thread-message"
          :class="{
            assistant: message.role === 'assistant',
            user: message.role === 'user',
            tool: isToolApprovalMessage(message) || isToolActivityMessage(message) || isToolResultMessage(message) || isToolCallMessage(message),
            pending: message.pending,
          }"
        >
          <div v-if="isToolApprovalMessage(message)" class="tool-approval-card">
            <div class="tool-approval-head">
              <Icon name="shield-check" />
              <div>
                <strong>等待工具审批 · {{ approvalRequest(message)?.tool_name }}</strong>
                <span>{{ approvalRequest(message)?.safety_level || 'safe' }} · {{ approvalPermissions(message) }}</span>
              </div>
            </div>
            <p v-if="approvalRequest(message)?.reason">{{ approvalRequest(message)?.reason }}</p>
            <details class="tool-message-detail">
              <summary>查看审批请求</summary>
              <pre><code>{{ approvalDetail(message) }}</code></pre>
            </details>
            <div class="tool-approval-actions">
              <button
                class="button compact-button primary"
                type="button"
                :disabled="approvingApproval"
                @click="emit('approveToolApproval', message)"
              >
                <Icon name="shield-check" />
                <span>{{ approvingApproval ? '处理中' : '批准' }}</span>
              </button>
              <button
                class="button compact-button danger"
                type="button"
                :disabled="approvingApproval"
                @click="emit('denyToolApproval', message)"
              >
                <Icon name="x" />
                <span>拒绝</span>
              </button>
            </div>
          </div>
          <div v-else-if="isToolActivityMessage(message)" class="tool-activity-card">
            <div class="tool-activity-head">
              <Icon name="wrench" />
              <div>
                <strong>工具活动</strong>
                <span>{{ toolActivitySummaryForMessage(message) }} · {{ toolActivityNamesForMessage(message) }}</span>
              </div>
            </div>
            <div class="tool-activity-list">
              <details
                v-for="(item, itemIndex) in toolActivityItems(message)"
                :key="`${item.role}-${itemIndex}-${item.tool_call_id || item.tool_calls?.[0]?.tool_call_id || ''}`"
                class="tool-activity-item"
              >
                <summary>
                  <span>{{ isToolResultMessage(item) ? toolResultTitle(item) : toolCallTitle(item) }}</span>
                  <code>{{ isToolResultMessage(item) ? toolResultSummary(item) : toolCallSummary(item) }}</code>
                </summary>
                <pre><code>{{ isToolResultMessage(item) ? toolResultDetail(item) : toolCallDetail(item) }}</code></pre>
              </details>
            </div>
          </div>
          <div v-else-if="isToolResultMessage(message)" class="tool-message-card">
            <div class="tool-message-head">
              <Icon name="file-text" />
              <div>
                <strong>{{ toolResultTitle(message) }}</strong>
                <span>{{ toolResultSummary(message) }}</span>
              </div>
            </div>
            <details class="tool-message-detail">
              <summary>查看完整工具返回</summary>
              <pre><code>{{ toolResultDetail(message) }}</code></pre>
            </details>
          </div>
          <div v-else-if="isToolCallMessage(message)" class="tool-message-card">
            <div class="tool-message-head">
              <Icon name="wrench" />
              <div>
                <strong>{{ toolCallTitle(message) }}</strong>
                <span>{{ toolCallSummary(message) }}</span>
              </div>
            </div>
            <details class="tool-message-detail">
              <summary>查看完整调用参数</summary>
              <pre><code>{{ toolCallDetail(message) }}</code></pre>
            </details>
          </div>
          <div v-else class="message-content">
            <div v-if="messageImages(message).length" class="message-images">
              <img
                v-for="(part, imageIndex) in messageImages(message)"
                :key="imageIndex"
                :src="imageSource(part) || undefined"
                :alt="String(part.metadata?.name || `图片 ${imageIndex + 1}`)"
              />
            </div>
            <div
              v-if="message.text || messageImages(message).length === 0"
              class="message-markdown"
              v-html="renderMarkdown(message.text || '无文本内容')"
            ></div>
          </div>
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
        <div v-if="loading && messages.length > 0" class="chat-thread-sync" role="status">
          正在同步上下文...
        </div>
      </div>

      <div v-if="primaryApprovalMessage" class="chat-approval-dock">
        <div class="chat-approval-dock-main">
          <Icon name="shield-check" />
          <div>
            <strong>等待审批 · {{ approvalToolName(primaryApprovalMessage) }}</strong>
            <span>{{ approvalSafetySummary(primaryApprovalMessage) }}</span>
          </div>
        </div>
        <div class="chat-approval-dock-actions">
          <button
            class="button compact-button primary"
            type="button"
            :disabled="approvingApproval"
            @click="emit('approveToolApproval', primaryApprovalMessage)"
          >
            <Icon name="shield-check" />
            <span>{{ approvingApproval ? '处理中' : '批准' }}</span>
          </button>
          <button
            class="button compact-button danger"
            type="button"
            :disabled="approvingApproval"
            @click="emit('denyToolApproval', primaryApprovalMessage)"
          >
            <Icon name="x" />
            <span>拒绝</span>
          </button>
        </div>
      </div>

      <form class="chat-composer" @submit.prevent="submit">
        <div class="chat-input-shell">
          <div v-if="selectedImages.length" class="composer-images">
            <div v-for="(part, index) in selectedImages" :key="index" class="composer-image">
              <img :src="imageSource(part) || undefined" :alt="String(part.metadata?.name || '待发送图片')" />
              <button type="button" title="移除图片" aria-label="移除图片" @click="removeImage(index)">
                <Icon name="x" />
              </button>
            </div>
          </div>
          <textarea
            ref="chatInput"
            v-model="model"
            rows="1"
            placeholder="给当前会话发送消息"
            :disabled="disabled || sending"
            :aria-describedby="error ? 'chat-composer-status' : undefined"
            @focus="modelPickerOpen = false"
            @input="resizeChatInput"
            @keydown.enter.exact.prevent="submit"
          ></textarea>
          <div class="chat-input-actions">
            <input
              ref="imageInput"
              class="visually-hidden"
              type="file"
              accept="image/jpeg,image/png,image/webp,image/gif"
              multiple
              tabindex="-1"
              @change="selectImages"
            />
            <button
              class="chat-attach-button"
              type="button"
              :disabled="disabled || sending || !supportsImageInput || selectedImages.length >= MAX_IMAGE_COUNT"
              :title="supportsImageInput ? '添加图片' : '当前模型不支持图片识别'"
              :aria-label="supportsImageInput ? '添加图片' : '当前模型不支持图片识别'"
              @click="openImagePicker"
            >
              <Icon name="image-plus" />
            </button>
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
                  <span>{{ option.label }}</span>
                  <Icon v-if="option.value === modelSelection" name="check" />
                  </button>
                </div>
              </Transition>
            </div>
            <button
              class="chat-send-button"
              type="submit"
              :disabled="disabled || sending || !canSubmit"
              :title="sendButtonLabel"
              :aria-label="sendButtonLabel"
            >
              <Icon name="send" />
            </button>
          </div>
        </div>
        <span
          v-if="error"
          id="chat-composer-status"
          class="chat-composer-hint is-error"
          role="alert"
        >
          {{ error }}
        </span>
      </form>
    </div>
  </section>
</template>
