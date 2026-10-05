<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
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
      <button type="button" :aria-expanded="!collapsed" @click="collapsed = !collapsed">
        {{ collapsed ? '展开输出' : '折叠输出' }}
      </button>
      <button type="button" @click="copy">复制</button>
      <span v-if="copyStatus" role="status">{{ copyStatus }}</span>
      <input
        v-show="!collapsed"
        v-model="query"
        type="search"
        :aria-label="label + ' 搜索'"
        placeholder="搜索输出"
        @keydown.enter.prevent="move(1)"
        @keydown.escape="query = ''"
      />
      <template v-if="query && !collapsed">
        <span role="status">{{ count ? current + 1 : 0 }}/{{ count }}</span>
        <button type="button" :disabled="!count" aria-label="上一个匹配" @click="move(-1)">
          ↑
        </button>
        <button type="button" :disabled="!count" aria-label="下一个匹配" @click="move(1)">↓</button>
      </template>
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
  gap: 6px;
  padding: 8px 10px;
  font-size: 11px;
  color: var(--color-text-muted);
}
.tool-output-actions button {
  background: transparent;
  color: inherit;
  border: 1px solid var(--color-border);
  border-radius: 5px;
  padding: 3px 7px;
  cursor: pointer;
}
.tool-output-actions input {
  flex: 1;
  min-width: 90px;
  max-width: 220px;
  padding: 4px 7px;
  border: 1px solid var(--color-border);
  border-radius: 5px;
  background: var(--color-surface);
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
  color: #cbd5e1;
  border-bottom: 1px solid #303c4e;
}
.tool-output--terminal input {
  color: #e4eaf3;
  background: #222e3e;
  border-color: #526078;
}
.tool-output--terminal button {
  border-color: #526078;
}
.tool-output--terminal .tool-output-search {
  background: transparent;
  color: #e4eaf3;
}
</style>
