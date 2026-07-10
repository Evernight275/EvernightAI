<script setup lang="ts">
import type { ViewKey } from '../views/navigation'
import Icon from './Icon.vue'

defineProps<{
  currentView: ViewKey
}>()

const emit = defineEmits<{
  navigate: [view: ViewKey]
}>()

const coreLinks: Array<{ view: ViewKey; icon: string; label: string }> = [
  { view: 'workbench', icon: 'layout-dashboard', label: '主页' },
  { view: 'chat', icon: 'message-square', label: '聊天' },
  { view: 'tools', icon: 'wrench', label: '工具列表' },
  { view: 'runs', icon: 'activity', label: '运行队列' },
  { view: 'analytics', icon: 'layout-dashboard', label: '数据统计' },
]

const manageLinks: Array<{ view: ViewKey; icon: string; label: string }> = [
  { view: 'agents', icon: 'table-2', label: '模型提供商配置' },
  { view: 'memories', icon: 'database', label: '记忆库' },
  { view: 'logs', icon: 'scroll-text', label: '日志' },
]
</script>

<template>
  <aside class="sidebar">
    <section class="sidebar-section">
      <h2 class="sidebar-title">核心</h2>
      <ul>
        <li v-for="link in coreLinks" :key="link.view">
          <button
            class="side-link"
            :class="{ 'is-active': currentView === link.view }"
            type="button"
            @click="emit('navigate', link.view)"
          >
            <Icon :name="link.icon" />
            <span>{{ link.label }}</span>
          </button>
        </li>
      </ul>
    </section>
    <section class="sidebar-section">
      <h2 class="sidebar-title">管理</h2>
      <ul>
        <li v-for="link in manageLinks" :key="link.view">
          <button
            class="side-link"
            :class="{ 'is-active': currentView === link.view }"
            type="button"
            @click="emit('navigate', link.view)"
          >
            <Icon :name="link.icon" />
            <span>{{ link.label }}</span>
          </button>
        </li>
      </ul>
    </section>
  </aside>
</template>
