<script setup lang="ts">
import Icon from './Icon.vue'
</script>

<template>
  <section class="panel">
    <div class="panel-head">
      <h2><Icon name="activity" /><span>执行流</span></h2>
      <span>本轮</span>
    </div>
    <div class="chart" aria-label="执行流图">
      <div v-for="index in 6" :key="index" class="bar"></div>
    </div>
    <div class="relations" aria-label="执行链路">
      <div class="relation-node">用户输入</div>
      <div class="connector"></div>
      <div class="relation-node">Agent 计划</div>
    </div>
    <div class="relation-column" aria-label="工具链路">
      <div class="relation-node">工具调用</div>
      <div class="connector"></div>
      <div class="relation-node">回复输出</div>
    </div>
  </section>
</template>
