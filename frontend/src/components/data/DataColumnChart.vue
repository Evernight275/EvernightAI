<script setup lang="ts">
import { computed, ref } from 'vue';
import { axisMaximum, compactNumber, type DayValue } from './dataDashboard';

const props = defineProps<{ title: string; unit: string; series: DayValue[] }>();
const active = ref<number | null>(null);
const maximum = computed(() => axisMaximum(Math.max(0, ...props.series.map((item) => item.value))));
const ticks = computed(() => [maximum.value, maximum.value / 2, 0]);
const total = computed(() => props.series.reduce((sum, item) => sum + item.value, 0));
const labels = computed(() => {
  const count = props.series.length;
  const picks = count <= 2 ? [0, count - 1] : [0, Math.floor((count - 1) / 2), count - 1];
  return [...new Set(picks)].filter((index) => index >= 0).map((index) => props.series[index]!);
});
const shortDay = (day: string): string => day.slice(5);
</script>

<template>
  <figure class="data-chart">
    <figcaption>
      <strong>{{ title }}</strong>
      <span>合计 {{ compactNumber(total) }} {{ unit }}</span>
    </figcaption>
    <p v-if="!series.length || !total" class="data-empty">这段时间没有数据。</p>
    <template v-else>
      <div class="data-columns">
        <div class="data-columns-axis" aria-hidden="true">
          <span v-for="tick in ticks" :key="tick">{{ compactNumber(tick) }}</span>
        </div>
        <div class="data-columns-plot" @mouseleave="active = null">
          <div
            v-for="(item, index) in series"
            :key="item.day"
            class="data-column"
            :class="{ 'is-active': active === index }"
            tabindex="0"
            :aria-label="`${item.day}：${compactNumber(item.value)} ${unit}`"
            @mouseenter="active = index"
            @focus="active = index"
            @blur="active = null"
          >
            <span
              class="data-column-bar"
              :style="{ height: `${(item.value / maximum) * 100}%` }"
            ></span>
            <span v-if="active === index" class="data-tooltip" role="tooltip">
              <strong>{{ compactNumber(item.value) }} {{ unit }}</strong>
              <small>{{ item.day }}</small>
            </span>
          </div>
        </div>
      </div>
      <div class="data-columns-days" aria-hidden="true">
        <span v-for="item in labels" :key="item.day">{{ shortDay(item.day) }}</span>
      </div>
      <details class="data-table">
        <summary>查看数据表</summary>
        <table>
          <thead>
            <tr>
              <th>日期（UTC）</th>
              <th>{{ unit }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in series" :key="item.day">
              <td>{{ item.day }}</td>
              <td>{{ item.value.toLocaleString('en-US') }}</td>
            </tr>
          </tbody>
        </table>
      </details>
    </template>
  </figure>
</template>
