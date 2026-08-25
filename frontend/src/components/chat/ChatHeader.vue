<script setup lang="ts">
import { computed } from 'vue'
import type { Session } from '../../api'
import { chatHeaderTitle } from './chatHeader'

const props = defineProps<{
  session: Session | null
}>()

const title = computed(() => chatHeaderTitle(props.session))
</script>

<template>
  <header class="chat-view-header">
    <div class="chat-content">
      <div class="chat-header-main">
        <div>
          <p class="chat-header-brand">EvernightAI</p>
          <h1 class="chat-header-title">{{ title }}</h1>
        </div>
      </div>
      <slot />
    </div>
  </header>
</template>
