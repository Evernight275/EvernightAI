<script setup lang="ts">
import type { ExecutionIndex } from '../../domain/workspace'
import EmptyValue from '../common/EmptyValue.vue'

defineProps<{
  index: ExecutionIndex
}>()
</script>

<template>
  <section>
    <h2>执行索引（{{ index.runs.length }}）</h2>
    <EmptyValue v-if="!index.runs.length" label="没有 Agent Run" />
    <ul v-else>
      <li v-for="run in index.runs" :key="run.run_id">
        <strong>{{ run.run_id }}</strong>
        <span> / {{ run.status || 'unknown' }}</span>
        <span> / {{ run.request.provider_id }} / {{ run.request.model_id }}</span>
        <span v-if="run.stop_reason"> / {{ run.stop_reason }}</span>
        <span> / tool rounds: {{ run.tool_rounds_used || 0 }}</span>
      </li>
    </ul>
  </section>
</template>
