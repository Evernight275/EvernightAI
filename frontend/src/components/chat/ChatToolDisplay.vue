<script setup lang="ts">
import { computed } from 'vue';
import { FileDiff, Terminal } from '@lucide/vue';
import { toolDisplay } from './toolDisplay';
import ToolOutput from '../common/ToolOutput.vue';

const props = defineProps<{ name: string; resultText?: string }>();
const display = computed(() => toolDisplay(props.name, props.resultText));
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
        退出码 {{ display.exitCode }}
      </span>
    </header>
    <ToolOutput :source="output" :label="name + ' 终端输出'" terminal>
      <div class="tool-terminal-scroll" tabindex="0" :aria-label="name + ' 终端输出'">
        <pre
          class="tool-terminal-command"
        ><span aria-hidden="true">$ </span>{{ display.command }}</pre>
        <div v-for="(block, index) in display.blocks" :key="index" class="tool-terminal-block">
          <span class="tool-terminal-stream">{{ block.stream }}</span>
          <pre :class="{ 'tool-terminal-stderr': block.stream === 'stderr' }">{{ block.text }}</pre>
        </div>
        <p v-if="!display.blocks.length" class="tool-terminal-empty">命令未产生输出。</p>
      </div>
    </ToolOutput>
    <p v-if="display.truncated" class="tool-display-notice">输出过长，已截断。</p>
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
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  font-weight: 400;
  line-height: 1.8;
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
  color: var(--color-text-muted);
  font-size: 12px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}
.tool-terminal {
  background: #18212f;
  border-color: #303c4e;
  color: #e4eaf3;
}
.tool-terminal header {
  background: #222e3e;
  border-color: #303c4e;
  color: #cbd5e1;
}
.tool-terminal-exit {
  border-radius: 5px;
  padding: 2px 6px;
  background: #23443b;
  color: #a6ebc9;
  font-size: 11px;
}
.tool-terminal-exit.is-error {
  background: #57303c;
  color: #ffbdc4;
}
.tool-terminal-scroll {
  padding: 12px;
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
  color: #a6ebc9;
}
.tool-terminal-block {
  margin-top: 12px;
}
.tool-terminal-stream {
  color: #a1b0c4;
  font-size: 10px;
}
.tool-terminal .tool-terminal-stderr {
  color: #ffbdc4;
}
.tool-terminal-empty {
  margin: 12px 0 0;
  color: #a1b0c4;
}
.tool-terminal .tool-display-notice {
  color: #a1b0c4;
  border-top: 1px solid #303c4e;
}
</style>
