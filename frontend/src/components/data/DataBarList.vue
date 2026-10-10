<script setup lang="ts">
import { computed } from 'vue';
import { compactNumber } from './dataDashboard';

export type DataBarItem = { label: string; value: number; note?: string };

const props = defineProps<{ title: string; unit: string; items: DataBarItem[] }>();
const maximum = computed(() => Math.max(1, ...props.items.map((item) => item.value)));
</script>

<template>
  <figure class="data-chart">
    <figcaption>
      <strong>{{ title }}</strong>
      <span>{{ unit }}</span>
    </figcaption>
    <p v-if="!items.length" class="data-empty">这段时间没有数据。</p>
    <ol v-else class="data-bars">
      <li
        v-for="item in items"
        :key="item.label"
        :title="`${item.label}：${item.value.toLocaleString('en-US')} ${unit}`"
      >
        <span class="data-bar-label">{{ item.label }}</span>
        <span class="data-bar-track" aria-hidden="true">
          <span class="data-bar-fill" :style="{ width: `${(item.value / maximum) * 100}%` }"></span>
        </span>
        <span class="data-bar-value">{{ compactNumber(item.value) }}</span>
        <small v-if="item.note" class="data-bar-note">{{ item.note }}</small>
      </li>
    </ol>
  </figure>
</template>
