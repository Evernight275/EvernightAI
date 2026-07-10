<script setup lang="ts">
import type { ToolDefinition } from '../api'
import { formatStatus, statusTone } from '../format'
import Icon from './Icon.vue'

defineProps<{
  tools: ToolDefinition[]
}>()
</script>

<template>
  <section class="panel">
    <div class="panel-head">
      <h2><Icon name="wrench" /><span>工具列表</span></h2>
      <span>{{ tools.length }} 个</span>
    </div>
    <div class="tool-list">
      <div v-if="tools.length === 0" class="tool-row">
        <Icon name="wrench" />
        <div>
          <strong>暂无工具</strong>
          <div class="tool-desc">后端未返回已注册工具</div>
        </div>
        <span class="tag">空</span>
      </div>
      <div v-for="tool in tools" v-else :key="tool.name" class="tool-row">
        <Icon name="wrench" />
        <div>
          <strong>{{ tool.name || '未命名工具' }}</strong>
          <div class="tool-desc">{{ tool.description || '无描述' }}</div>
        </div>
        <span
          class="tag"
          :class="statusTone(tool.requires_approval ? '需审批' : tool.safety_level || '在线')"
        >
          {{ tool.requires_approval ? '需审批' : formatStatus(tool.safety_level || '在线') }}
        </span>
      </div>
    </div>
  </section>
</template>
