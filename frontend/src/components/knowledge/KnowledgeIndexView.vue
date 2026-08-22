<script setup lang="ts">
import type { KnowledgeIndex } from '../../domain/workspace'
import EmptyValue from '../common/EmptyValue.vue'

defineProps<{
  index: KnowledgeIndex
}>()
</script>

<template>
  <section>
    <h2>知识索引（{{ index.memories.length }}）</h2>
    <EmptyValue v-if="!index.memories.length" label="没有记忆" />
    <ul v-else>
      <li v-for="memory in index.memories" :key="memory.memory_id">
        <strong>{{ memory.memory_id }}</strong>
        <span> / {{ memory.kind || 'fact' }} / {{ memory.scope || 'global' }}</span>
        <span> / {{ memory.is_enabled === false ? '停用' : '启用' }}</span>
        <p>{{ memory.content }}</p>
        <p v-if="memory.tags?.length">标签：{{ memory.tags.join(', ') }}</p>
      </li>
    </ul>
  </section>
</template>
