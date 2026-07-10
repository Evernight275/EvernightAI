<script setup lang="ts">
import type { ToolDefinition } from '../api'
import ToolList from '../components/ToolList.vue'

defineProps<{
  tools: ToolDefinition[]
}>()
</script>

<template>
  <ToolList :tools="tools" />
</template>
