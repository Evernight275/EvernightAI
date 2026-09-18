<script setup lang="ts">
import WorkspaceIssues from '../workspace/WorkspaceIssues.vue'
import {
  useChatPrerequisites,
  type ChatPrerequisitesProps,
} from './chatPrerequisites'

const props = defineProps<ChatPrerequisitesProps>()
const { notice } = useChatPrerequisites(props)
</script>

<template>
  <section class="chat-prerequisites">
    <h2>前置状态</h2>
    <p>Workspace：{{ state }}</p>
    <p>Provider：{{ providerCount }}</p>
    <p>Tools：{{ toolCount }}</p>
    <p v-if="notice">{{ notice }}</p>
    <WorkspaceIssues :issues="issues" />
  </section>
</template>
