<script setup lang="ts">
import type { WorkspaceIssue } from '../../domain/workspace'

defineProps<{
  issues: WorkspaceIssue[]
}>()
</script>

<template>
  <section v-if="issues.length" class="settings-issues-section">
    <h2>加载问题（{{ issues.length }}）</h2>
    <ul>
      <li v-for="issue in issues" :key="`${issue.concept}:${issue.resource}`">
        {{ issue.concept }} / {{ issue.resource }}：{{ issue.message }}
        <span v-if="issue.status">（HTTP {{ issue.status }}）</span>
      </li>
    </ul>
  </section>
</template>
