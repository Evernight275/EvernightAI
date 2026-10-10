<script setup lang="ts">
import { onMounted } from 'vue';
import { controlPanelPath, useServiceStatus } from './serviceStatus';

const { state, stateLabel, detail, checkedTime, busy, check, entering, enterError, enter } =
  useServiceStatus({ navigate: (target) => window.location.assign(target) });

onMounted(check);
</script>

<template>
  <main class="service-status">
    <section class="service-status__card" aria-labelledby="service-status-title">
      <p class="service-status__brand">EvernightAI</p>
      <h1 id="service-status-title">服务状态</h1>
      <p class="service-status__value" role="status">
        <span class="settings-status-dot" :class="`is-${state}`" aria-hidden="true"></span
        >{{ stateLabel }}
      </p>
      <p v-if="detail" class="settings-status-meta">{{ detail }}</p>
      <p v-if="checkedTime" class="settings-status-meta">最后检查：{{ checkedTime }}</p>
      <div class="service-status__actions">
        <button type="button" :disabled="busy" @click="check">刷新</button>
        <a :href="controlPanelPath" :aria-busy="entering" @click.prevent="enter">进入控制面板</a>
      </div>
      <p v-if="enterError" class="settings-status-meta" role="alert">{{ enterError }}</p>
    </section>
  </main>
</template>
