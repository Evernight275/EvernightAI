<script setup lang="ts">
import { computed } from 'vue';
import { compactNumber, percentText, ratio, type TokenCost } from './dataDashboard';

const props = defineProps<{ total: TokenCost; models: TokenCost[] }>();

// Where the tokens went. Cache reads are split out only when the provider reported them.
const segments = computed(() => {
  const { prompt, completion, cached } = props.total;
  const parts = [
    { id: 'cached', label: '缓存读取输入', value: cached ?? 0 },
    {
      id: 'input',
      label: cached === undefined ? '输入' : '其余输入',
      value: Math.max(0, (prompt ?? 0) - (cached ?? 0)),
    },
    { id: 'output', label: '输出', value: completion ?? 0 },
  ].filter((part) => part.value > 0);
  const sum = parts.reduce((all, part) => all + part.value, 0);
  return parts.map((part) => ({ ...part, share: part.value / sum }));
});
const perRun = (cost: TokenCost): string => compactNumber(ratio(cost.total, cost.runs));
const cacheShare = (cost: TokenCost): string => percentText(ratio(cost.cached, cost.observed));
</script>

<template>
  <figure class="data-chart data-token-cost">
    <figcaption>
      <strong>Token 成本</strong>
      <span>平均每次运行 {{ perRun(total) }} Token</span>
    </figcaption>
    <p v-if="!segments.length" class="data-empty">这段时间没有数据。</p>
    <template v-else>
      <div
        class="data-stack"
        role="img"
        :aria-label="segments.map((s) => `${s.label} ${percentText(s.share)}`).join('，')"
      >
        <span
          v-for="segment in segments"
          :key="segment.id"
          :class="`is-${segment.id}`"
          :style="{ flexGrow: segment.value }"
          :title="`${segment.label}：${segment.value.toLocaleString('en-US')} Token`"
        ></span>
      </div>
      <ul class="data-stack-legend">
        <li v-for="segment in segments" :key="segment.id">
          <i :class="`is-${segment.id}`" aria-hidden="true"></i>
          <span>{{ segment.label }}</span>
          <strong>{{ compactNumber(segment.value) }}</strong>
          <small>{{ percentText(segment.share) }}</small>
        </li>
      </ul>
      <div v-if="models.length" class="data-table-scroll">
        <table class="data-cost-table">
          <thead>
            <tr>
              <th scope="col">模型</th>
              <th scope="col">运行</th>
              <th scope="col">输入</th>
              <th scope="col">输出</th>
              <th scope="col">合计</th>
              <th scope="col">每次运行</th>
              <th scope="col">缓存读取占比</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="model in models" :key="model.label">
              <th scope="row" :title="model.label">{{ model.label }}</th>
              <td>{{ compactNumber(model.runs) }}</td>
              <td>{{ compactNumber(model.prompt) }}</td>
              <td>{{ compactNumber(model.completion) }}</td>
              <td>{{ compactNumber(model.total) }}</td>
              <td>{{ perRun(model) }}</td>
              <td>{{ cacheShare(model) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="data-footnote">
        按 Token
        数量统计；系统没有配置各模型的单价，因此不折算金额。缓存读取占比只统计服务商返回了缓存用量的输入。
      </p>
    </template>
  </figure>
</template>
