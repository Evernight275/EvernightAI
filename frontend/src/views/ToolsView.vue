<script setup lang="ts">
import type { ToolDefinition } from '../api'
import Icon from '../components/Icon.vue'
import ToolList from '../components/ToolList.vue'

defineProps<{
  tools: ToolDefinition[]
}>()
</script>

<template>
  <section class="content-grid">
    <div class="primary-stack">
      <ToolList :tools="tools" />
    </div>
    <aside class="side-stack">
      <section class="panel view-panel">
        <div class="panel-head">
          <h2><Icon name="shield-check" /><span>工具状态</span></h2>
          <span>{{ tools.length }} 个</span>
        </div>
        <p>工具来自后端 runtime 注册表。敏感工具会在 Agent run 中进入审批流程。</p>
      </section>
    </aside>
  </section>
</template>
