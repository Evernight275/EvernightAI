<script setup lang="ts">
import {
  useChatToolActivity,
  type ChatToolActivityProps,
} from './chatToolActivity'

const props = defineProps<ChatToolActivityProps>()
const { activities } = useChatToolActivity(props)
</script>

<template>
  <section>
    <h2>工具调用（{{ activities.length }}）</h2>
    <p v-if="!activities.length">还没有工具调用</p>
    <ol v-else>
      <li v-for="activity in activities" :key="activity.key">
        {{ activity.name }} / {{ activity.status }}
      </li>
    </ol>
  </section>
</template>
