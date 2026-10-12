<script setup lang="ts">
import { computed, onMounted } from 'vue';
import { controlPanelPath, useServiceStatus } from './serviceStatus';

const {
  state,
  stateLabel,
  detail,
  checkedTime,
  latencyMs,
  busy,
  check,
  entering,
  enterError,
  enter,
} = useServiceStatus({ navigate: (target) => window.location.assign(target) });

// What each unauthenticated probe said, as far as the last check got.
const probes = computed(() => {
  const reached = state.value === 'ready' || state.value === 'starting';
  const pending = state.value === 'checking';
  return [
    {
      name: '服务进程',
      path: '/health',
      value: pending ? '…' : reached ? '正常' : '无响应',
      bad: state.value === 'offline',
    },
    {
      name: '运行时',
      path: '/ready',
      value: pending || !reached ? '—' : state.value === 'ready' ? '就绪' : '未就绪',
      bad: state.value === 'starting',
    },
    {
      name: '响应',
      path: '/health 往返',
      value: latencyMs.value === null ? '—' : `${latencyMs.value} ms`,
      bad: false,
    },
  ];
});

onMounted(check);
</script>

<template>
  <main class="home">
    <div class="home-card">
      <header class="home-header">
        <h1>EvernightAI</h1>
        <p>
          一个小型分层 AI runtime，把模型提供商、技能、工具、上下文、记忆和 agent run 组织在一起。
        </p>
      </header>

      <section class="home-status" aria-labelledby="home-status-title">
        <div class="home-status-heading">
          <h2 id="home-status-title">服务状态</h2>
          <span v-if="checkedTime">最后检查 {{ checkedTime }}</span>
        </div>
        <p class="home-state" role="status">
          <span class="settings-status-dot" :class="`is-${state}`" aria-hidden="true"></span
          >{{ stateLabel }}
        </p>
        <p v-if="detail" class="home-detail">{{ detail }}</p>
        <dl class="home-probes">
          <div v-for="probe in probes" :key="probe.name">
            <dt>
              {{ probe.name }}<small>{{ probe.path }}</small>
            </dt>
            <dd :class="{ 'is-bad': probe.bad }">{{ probe.value }}</dd>
          </div>
        </dl>
      </section>

      <div class="home-actions">
        <a class="home-enter" :href="controlPanelPath" :aria-busy="entering" @click.prevent="enter"
          >进入控制面板</a
        >
        <button type="button" :disabled="busy" @click="check">
          {{ busy ? '检查中…' : '重新检查' }}
        </button>
      </div>
      <p v-if="enterError" class="home-detail" role="alert">{{ enterError }}</p>
    </div>
  </main>
</template>
