<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import {
  Check,
  ChevronDown,
  ChevronUp,
  ChevronsDownUp,
  ChevronsUpDown,
  Copy,
  Search,
} from '@lucide/vue';
import { outputParts } from './outputText';

const props = defineProps<{ source: string; label: string; terminal?: boolean }>();
const collapsed = ref(false);
const query = ref('');
const current = ref(0);
const copyStatus = ref('');
const root = ref<HTMLElement>();
const parts = computed(() => outputParts(props.source, query.value));
const count = computed(() => parts.value.filter((part) => part.match !== undefined).length);
watch([query, () => props.source], () => {
  current.value = 0;
  copyStatus.value = '';
});
async function locate() {
  await nextTick();
  root.value
    ?.querySelector('mark.is-current')
    ?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
}
watch([query, current], locate);
function move(direction: number) {
  if (count.value) current.value = (current.value + direction + count.value) % count.value;
}
async function copy() {
  try {
    await navigator.clipboard.writeText(props.source);
    copyStatus.value = '已复制';
  } catch {
    copyStatus.value = '复制失败，请选中文本复制';
  }
}
defineExpose({
  async expand() {
    collapsed.value = false;
    query.value = '';
    await nextTick();
  },
});
</script>

<template>
  <div ref="root" class="tool-output" :class="{ 'tool-output--terminal': terminal }">
    <div class="tool-output-actions">
      <label v-show="!collapsed" class="tool-output-search-field">
        <Search :size="13" aria-hidden="true" />
        <input
          v-model="query"
          type="search"
          :aria-label="label + ' 搜索'"
          placeholder="搜索输出"
          @keydown.enter.prevent="move(1)"
          @keydown.escape="query = ''"
        />
      </label>
      <template v-if="query && !collapsed">
        <span role="status">{{ count ? current + 1 : 0 }}/{{ count }}</span>
        <button
          type="button"
          :disabled="!count"
          aria-label="上一个匹配"
          title="上一个匹配"
          @click="move(-1)"
        >
          <ChevronUp :size="14" aria-hidden="true" />
        </button>
        <button
          type="button"
          :disabled="!count"
          aria-label="下一个匹配"
          title="下一个匹配"
          @click="move(1)"
        >
          <ChevronDown :size="14" aria-hidden="true" />
        </button>
      </template>
      <span class="tool-output-spacer"></span>
      <span v-if="copyStatus" role="status">{{ copyStatus }}</span>
      <button type="button" aria-label="复制" title="复制" @click="copy">
        <Check v-if="copyStatus === '已复制'" :size="14" aria-hidden="true" />
        <Copy v-else :size="14" aria-hidden="true" />
      </button>
      <button
        type="button"
        :aria-expanded="!collapsed"
        :aria-label="collapsed ? '展开输出' : '折叠输出'"
        :title="collapsed ? '展开输出' : '折叠输出'"
        @click="collapsed = !collapsed"
      >
        <ChevronsUpDown v-if="collapsed" :size="14" aria-hidden="true" />
        <ChevronsDownUp v-else :size="14" aria-hidden="true" />
      </button>
    </div>
    <div v-show="!collapsed">
      <pre
        v-if="query"
        class="tool-output-search"
        tabindex="0"
        :aria-label="label + ' 搜索结果'"
      ><template v-for="(part, index) in parts" :key="index"><mark v-if="part.match !== undefined" :class="{ 'is-current': part.match === current }">{{ part.text }}</mark><template v-else>{{ part.text }}</template></template></pre>
      <slot v-else />
    </div>
  </div>
</template>

<style scoped>
.tool-output {
  min-width: 0;
  max-width: 100%;
}
.tool-output-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  padding: 6px 8px;
  font-size: 11px;
  color: var(--color-muted);
}
.tool-output-spacer {
  flex: 1;
}
.tool-output-actions button {
  display: inline-grid;
  place-items: center;
  width: 26px;
  min-height: 26px;
  padding: 0;
  border-color: transparent;
  border-radius: 6px;
  background: transparent;
  color: inherit;
  cursor: pointer;
}
.tool-output-actions button:hover:not(:disabled) {
  border-color: transparent;
  background: var(--color-surface-strong);
  color: var(--color-text);
}
.tool-output-search-field {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 0 1 200px;
  min-width: 96px;
  padding: 0 8px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-bg);
}
.tool-output-search-field:focus-within {
  border-color: var(--color-muted);
}
.tool-output-search-field input {
  flex: 1;
  width: 100%;
  min-width: 0;
  min-height: 24px;
  padding: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--color-text);
  font: inherit;
}
.tool-output-search {
  margin: 0;
  padding: 12px;
  max-height: 360px;
  overflow: auto;
  font: 12px/1.8 var(--font-mono);
  white-space: pre;
  -webkit-font-smoothing: antialiased;
}
mark {
  background: #fef08a;
  color: #422006;
}
mark.is-current {
  background: #fb923c;
  outline: 1px solid #c2410c;
}
.tool-output--terminal .tool-output-actions {
  border-bottom: 1px solid var(--terminal-border);
  color: var(--terminal-muted);
}
.tool-output--terminal .tool-output-search-field {
  border-color: var(--terminal-border);
  background: var(--terminal-surface);
}
.tool-output--terminal .tool-output-search-field:focus-within {
  border-color: var(--terminal-muted);
}
.tool-output--terminal input {
  color: var(--terminal-text);
}
.tool-output--terminal button:hover:not(:disabled) {
  background: var(--terminal-border);
  color: var(--terminal-text);
}
.tool-output--terminal .tool-output-search {
  background: transparent;
  color: var(--terminal-text);
}
</style>
