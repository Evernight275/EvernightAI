<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue';
import type { ChatToolActivityEntry } from './chatToolActivity';
import { timeLabel, toolTimeline } from './toolTimeline';

const props = defineProps<{ activities: ChatToolActivityEntry[] }>();
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
const hasFailure = computed(() => timeline.value?.rows.some((row) => row.status === 'failed'));
</script>

<template>
  <figure v-if="timeline" class="tool-timeline">
    <figcaption>
      <strong>调用时间线</strong>
      <span>从首次调用起 {{ timeLabel(timeline.spanMs) }}</span>
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
            :class="`is-${row.status}`"
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
    <p v-if="hasFailure" class="tool-timeline-legend">
      <span><i class="is-completed"></i>完成</span><span><i class="is-failed"></i>失败</span>
    </p>
  </figure>
</template>
