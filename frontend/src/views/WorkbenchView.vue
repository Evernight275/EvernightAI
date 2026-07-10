<script setup lang="ts">
import Icon from '../components/Icon.vue'
import type { ViewKey } from './navigation'

const emit = defineEmits<{
  navigate: [view: ViewKey]
}>()
</script>

<template>
  <section class="home-welcome">
    <h2>欢迎使用 EvernightAI</h2>
    <p>一个强大的 AI Agent 运行时平台，支持多模型、工具调用和会话管理</p>

    <div class="quick-start-grid">
      <button class="quick-start-card" type="button" @click="emit('navigate', 'chat')">
        <Icon name="message-circle" class="icon" />
        <h3>开始对话</h3>
        <p>创建新会话或继续现有对话，体验 AI 助手的强大能力</p>
      </button>

      <button class="quick-start-card" type="button" @click="emit('navigate', 'tools')">
        <Icon name="wrench" class="icon" />
        <h3>查看工具</h3>
        <p>浏览已注册的工具列表，了解 Agent 可以调用的功能</p>
      </button>

      <button class="quick-start-card" type="button" @click="emit('navigate', 'agents')">
        <Icon name="cpu" class="icon" />
        <h3>配置模型</h3>
        <p>管理模型提供商，选择适合你任务的 AI 模型</p>
      </button>

      <button class="quick-start-card" type="button" @click="emit('navigate', 'analytics')">
        <Icon name="chart-column" class="icon" />
        <h3>查看统计</h3>
        <p>查看 Agent run、会话、工具调用和记忆写入数据</p>
      </button>
    </div>
  </section>
</template>
