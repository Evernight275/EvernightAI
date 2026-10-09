<script setup lang="ts">
import { computed } from 'vue';
import { CircleCheck, CircleX, FileDiff, LoaderCircle, Terminal } from '@lucide/vue';
import { pendingCommand, toolDisplay } from './toolDisplay';
import ToolOutput from '../common/ToolOutput.vue';

const props = defineProps<{
  name: string;
  resultText?: string;
  argumentsText?: string;
  running?: boolean;
}>();
const display = computed(() =>
  props.running ? undefined : toolDisplay(props.name, props.resultText),
);
const pending = computed(() =>
  props.running ? pendingCommand(props.name, props.argumentsText) : undefined,
);
const output = computed(() => {
  const value = display.value;
  return value?.kind === 'diff'
    ? value.lines.map((line) => line.text).join('\n')
    : value?.kind === 'terminal'
      ? [
          '$ ' + value.command,
          ...value.blocks.map((block) => block.stream + '\n' + block.text),
        ].join('\n')
      : '';
});
</script>

<template>
  <section v-if="display?.kind === 'diff'" class="tool-display tool-diff" aria-label="文件差异">
    <header>
      <FileDiff :size="15" aria-hidden="true" />
      <span class="tool-display-title" :title="display.path">{{ display.path }}</span>
      <span v-if="!display.unavailable" class="tool-diff-stats">
        <span class="tool-diff-added">+{{ display.added }}</span>
        <span class="tool-diff-removed">−{{ display.removed }}</span>
      </span>
    </header>
    <p v-if="display.unavailable" class="tool-display-notice">
      文件已写入，此记录没有可显示的差异（旧记录、大文件或非 UTF-8 文本）。
    </p>
    <p v-else-if="!display.lines.length && !display.truncated" class="tool-display-notice">
      文件内容无变化。
    </p>
    <ToolOutput v-else :source="output" :label="name + ' 文件差异'">
      <div class="tool-diff-scroll" tabindex="0" :aria-label="name + ' 文件差异'">
        <div class="tool-diff-lines">
          <div
            v-for="(line, index) in display.lines"
            :key="index"
            class="tool-diff-line"
            :class="'tool-diff-line--' + line.kind"
          >
            <span class="tool-diff-number" aria-hidden="true">{{ line.oldLine }}</span>
            <span class="tool-diff-number" aria-hidden="true">{{ line.newLine }}</span>
            <code>{{ line.text }}</code>
          </div>
        </div>
      </div>
    </ToolOutput>
    <p v-if="display.truncated" class="tool-display-notice">
      差异过长，仅显示部分内容；行数统计仅包含已显示的差异。
    </p>
  </section>
  <section
    v-else-if="display?.kind === 'terminal'"
    class="tool-display tool-terminal"
    aria-label="命令终端"
  >
    <header>
      <Terminal :size="15" aria-hidden="true" />
      <span class="tool-display-title" :title="display.directory">
        {{ display.directory || '命令输出' }}
      </span>
      <span class="tool-terminal-exit" :class="{ 'is-error': display.exitCode !== 0 }">
        <CircleX v-if="display.exitCode !== 0" :size="13" aria-hidden="true" />
        <CircleCheck v-else :size="13" aria-hidden="true" />
        退出码 {{ display.exitCode }}
      </span>
    </header>
    <ToolOutput :source="output" :label="name + ' 终端输出'" terminal>
      <div class="tool-terminal-scroll" tabindex="0" :aria-label="name + ' 终端输出'">
        <pre
          class="tool-terminal-command"
        ><span class="tool-terminal-prompt" aria-hidden="true">$ </span>{{ display.command }}</pre>
        <div
          v-for="(block, index) in display.blocks"
          :key="index"
          class="tool-terminal-block"
          :class="'tool-terminal-block--' + block.stream"
        >
          <span
            v-if="block.stream === 'stderr' || display.blocks.length > 1"
            class="tool-terminal-stream"
            >{{ block.stream }}</span
          >
          <pre
            :class="{ 'tool-terminal-stderr': block.stream === 'stderr' }"
          ><span v-for="(segment, part) in block.segments" :key="part" :class="[segment.color && 'ansi-' + segment.color, { 'ansi-bold': segment.bold, 'ansi-dim': segment.dim }]">{{ segment.text }}</span></pre>
        </div>
        <p v-if="!display.blocks.length" class="tool-terminal-empty">命令未产生输出。</p>
      </div>
    </ToolOutput>
    <p v-if="display.truncated" class="tool-display-notice">输出过长，已截断。</p>
  </section>
  <section v-else-if="pending" class="tool-display tool-terminal" aria-label="命令终端">
    <header>
      <Terminal :size="15" aria-hidden="true" />
      <span class="tool-display-title">命令执行</span>
      <span class="tool-terminal-exit is-running" role="status">
        <LoaderCircle class="tool-terminal-spinner" :size="13" aria-hidden="true" />
        执行中
      </span>
    </header>
    <div class="tool-terminal-scroll">
      <pre
        class="tool-terminal-command"
      ><span class="tool-terminal-prompt" aria-hidden="true">$ </span>{{ pending }}<span class="tool-terminal-cursor" aria-hidden="true"></span></pre>
    </div>
  </section>
</template>

<style scoped>
.tool-display {
  min-width: 0;
  max-width: 100%;
  margin: 10px 0;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: 12px;
  font-size: 12px;
}
.tool-display header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
}
.tool-display header > svg,
.tool-diff-stats,
.tool-terminal-exit {
  flex-shrink: 0;
}
.tool-display-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tool-diff-stats {
  display: flex;
  gap: 8px;
}
.tool-diff-added {
  color: #167047;
}
.tool-diff-removed {
  color: #b42335;
}
.tool-diff-scroll,
.tool-terminal-scroll {
  max-height: 360px;
  overflow: auto;
  overscroll-behavior: contain;
}
.tool-diff-lines {
  width: max-content;
  min-width: 100%;
}
.tool-diff-line {
  display: grid;
  grid-template-columns: 42px 42px 1fr;
  padding-right: 12px;
  min-height: 22px;
}
.tool-diff-line,
.tool-terminal pre {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 400;
  line-height: 1.7;
  font-variant-ligatures: none;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  tab-size: 2;
}
.tool-diff-line code {
  padding-left: 8px;
  font: inherit;
  white-space: pre;
}
.tool-diff-number {
  padding-right: 8px;
  border-right: 1px solid #00000008;
  color: #667085;
  text-align: right;
  user-select: none;
}
.tool-diff-line--added {
  background: #eaf8ee;
  color: #14532d;
}
.tool-diff-line--removed {
  background: #fff0f0;
  color: #9f1239;
}
.tool-diff-line--hunk {
  background: #eff6ff;
  color: #41658b;
}
.tool-diff-line--header,
.tool-diff-line--note {
  color: #667085;
}
.tool-display-notice {
  margin: 0;
  padding: 10px 12px;
  color: var(--color-muted);
  font-size: 12px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}
.tool-terminal {
  border-color: var(--terminal-border);
  background: var(--terminal-bg);
  color: var(--terminal-text);
}
.tool-terminal header {
  border-color: var(--terminal-border);
  background: var(--terminal-surface);
  color: var(--terminal-muted);
}
.tool-terminal .tool-display-title {
  font-family: var(--font-mono);
  font-size: 11px;
}
.tool-terminal-exit {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border-radius: 999px;
  padding: 2px 8px 2px 6px;
  background: #1f3d31;
  color: var(--terminal-prompt);
  font-size: 11px;
  line-height: 1.5;
}
.tool-terminal-exit.is-error {
  background: #4a262b;
  color: var(--terminal-error);
}
.tool-terminal-exit.is-running {
  background: var(--terminal-border);
  color: var(--terminal-text);
}
.tool-terminal-spinner {
  animation: tool-terminal-spin 900ms linear infinite;
}
.tool-terminal-scroll {
  padding: 12px 14px;
  scrollbar-color: var(--terminal-border) transparent;
}
.tool-terminal pre {
  margin: 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: inherit;
  white-space: pre;
  overflow-wrap: normal;
}
.tool-terminal .tool-terminal-command {
  font-weight: 600;
}
.tool-terminal-prompt {
  color: var(--terminal-prompt);
  user-select: none;
}
.tool-terminal-cursor {
  display: inline-block;
  width: 7px;
  height: 14px;
  margin-left: 4px;
  background: var(--terminal-muted);
  vertical-align: -2px;
  animation: tool-terminal-blink 1.1s steps(2, start) infinite;
}
.tool-terminal-block {
  margin-top: 10px;
}
.tool-terminal-block--stderr {
  width: max-content;
  min-width: 100%;
  padding-left: 10px;
  border-left: 2px solid var(--terminal-error);
}
.tool-terminal-stream {
  display: block;
  margin-bottom: 2px;
  color: var(--terminal-muted);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  user-select: none;
}
.tool-terminal .tool-terminal-stderr {
  color: var(--terminal-error);
}
.tool-terminal-empty {
  margin: 10px 0 0;
  color: var(--terminal-muted);
}
.tool-terminal .tool-display-notice {
  color: var(--terminal-muted);
  border-top: 1px solid var(--terminal-border);
}
.ansi-bold {
  font-weight: 700;
}
.ansi-dim {
  opacity: 0.65;
}
.ansi-black,
.ansi-bright-black {
  color: #8b8b93;
}
.ansi-red,
.ansi-bright-red {
  color: #ff9aa2;
}
.ansi-green,
.ansi-bright-green {
  color: #7fd6a4;
}
.ansi-yellow,
.ansi-bright-yellow {
  color: #e6c370;
}
.ansi-blue,
.ansi-bright-blue {
  color: #8ab4f8;
}
.ansi-magenta,
.ansi-bright-magenta {
  color: #d3a6f5;
}
.ansi-cyan,
.ansi-bright-cyan {
  color: #7ed3d9;
}
.ansi-white,
.ansi-bright-white {
  color: #f5f5f7;
}
@keyframes tool-terminal-spin {
  to {
    transform: rotate(360deg);
  }
}
@keyframes tool-terminal-blink {
  to {
    visibility: hidden;
  }
}
@media (prefers-reduced-motion: reduce) {
  .tool-terminal-spinner,
  .tool-terminal-cursor {
    animation: none;
  }
}
</style>
