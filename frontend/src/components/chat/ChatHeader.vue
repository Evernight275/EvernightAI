<script setup lang="ts">
import { Menu, PanelRight } from '@lucide/vue'
import { useChatHeader, type ChatHeaderProps } from './chatHeader'

const props = defineProps<ChatHeaderProps>()
defineEmits<{ details: []; navigation: [] }>()
const { title, stateLabel } = useChatHeader(props)
</script>

<template>
  <header class="chat-view-header">
    <div class="chat-content">
      <div class="chat-header-main">
        <button class="icon-button chat-navigation-toggle" type="button"
          aria-label="会话管理" title="会话管理" @click="$emit('navigation')">
          <Menu :size="18" aria-hidden="true" />
        </button>
        <div class="chat-header-heading">
          <h1 class="chat-header-title">{{ title }}</h1>
          <p class="chat-header-status" role="status">{{ stateLabel }}</p>
        </div>
        <button class="icon-button" type="button" aria-label="运行详情"
          title="运行详情" aria-haspopup="dialog" :aria-expanded="detailsOpen"
          aria-controls="chat-run-details" @click="$emit('details')">
          <PanelRight :size="18" aria-hidden="true" />
        </button>
      </div>
    </div>
  </header>
</template>
