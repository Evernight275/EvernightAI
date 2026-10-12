<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue';
import type { ChatToolActivityEntry } from './chatToolActivity';
import { timeLabel, toolTimeline } from './toolTimeline';

const props = defineProps<{ activities: ChatToolActivityEntry[]; title?: string }>();
const active = ref<string | null>(null);
const now = ref(Date.now());
let timer: ReturnType<typeof setInterval> | undefined;
// A running call's bar grows until it finishes.
watch(
  () => props.activities.some((activity) => activity.status === 'running'),
  (running) => {
    clearInterval(timer);
    now.value = Date.now();
    timer = running
      ? setInterval(() => {
          now.value = Date.now();
        }, 1000)
      : undefined;
  },
  { immediate: true },
);
onUnmounted(() => clearInterval(timer));
const timeline = computed(() => toolTimeline(props.activities, now.value));
const toneLabels = { tool: '工具调用', model: '模型响应', wait: '等待审批', failed: '失败' };
// A legend only when the bars differ in meaning; one kind of bar is named by the title.
const legend = computed(() => {
  const tones = new Set(timeline.value?.rows.map((row) => row.tone));
  const shown = (Object.keys(toneLabels) as (keyof typeof toneLabels)[]).filter((tone) =>
    tones.has(tone),
  );
  return shown.length > 1 ? shown.map((tone) => ({ tone, label: toneLabels[tone] })) : [];
});
</script>

<template>
  <figure v-if="timeline" class="tool-timeline">
    <figcaption>
      <strong>{{ title ?? '调用时间线' }}</strong>
      <span>共 {{ timeLabel(timeline.spanMs) }}</span>
    </figcaption>
    <ol class="tool-timeline-rows" @mouseleave="active = null">
      <li
        v-for="row in timeline.rows"
        :key="row.key"
        class="tool-timeline-row"
        :class="{ 'is-active': active === row.key }"
        tabindex="0"
        :aria-label="`${row.name}：${row.statusLabel}，开始于 ${timeLabel(row.offsetMs)}，耗时 ${timeLabel(row.durationMs)}`"
        @mouseenter="active = row.key"
        @focus="active = row.key"
        @blur="active = null"
      >
        <span class="tool-timeline-name">{{ row.name }}</span>
        <span class="tool-timeline-track">
          <span
            class="tool-timeline-bar"
            :class="[`is-${row.tone}`, { 'is-running': row.status === 'running' }]"
            :style="{ left: `min(${row.left}%, calc(100% - 3px))`, width: `${row.width}%` }"
          ></span>
          <span
            v-if="active === row.key"
            class="tool-timeline-tooltip"
            :class="{ 'is-end': row.left > 50 }"
            :style="
              row.left > 50 ? { right: `${100 - row.left - row.width}%` } : { left: `${row.left}%` }
            "
            role="tooltip"
          >
            <strong>{{ timeLabel(row.durationMs) }}</strong>
            <small>{{ row.name }} · {{ row.statusLabel }}</small>
            <small>开始于 {{ timeLabel(row.offsetMs) }}</small>
          </span>
        </span>
      </li>
    </ol>
    <div class="tool-timeline-axis" aria-hidden="true">
      <span></span>
      <span class="tool-timeline-ticks">
        <span v-for="tick in timeline.ticks" :key="tick.position">{{ tick.label }}</span>
      </span>
    </div>
    <p v-if="legend.length" class="tool-timeline-legend">
      <span v-for="item in legend" :key="item.tone"
        ><i :class="`is-${item.tone}`"></i>{{ item.label }}</span
      >
    </p>
  </figure>
</template>
