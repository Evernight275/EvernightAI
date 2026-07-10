<script setup lang="ts">
import Icon from '../components/Icon.vue'

defineProps<{
  status: string
}>()
</script>

<template>
  <section class="panel view-panel">
    <div class="panel-head">
      <h2><Icon name="database" /><span>记忆库</span></h2>
      <span class="tag" :class="status === '已同步' ? 'success' : 'danger'">{{ status }}</span>
    </div>
    <div class="memory-empty">
      <div class="memory-empty-content">
        <Icon name="database" class="memory-empty-icon" />
        <div>
          <strong>记忆库功能即将推出</strong>
          <p>记忆库将支持查看、搜索和管理 Agent 的持久化记忆。您可以在这里筛选记忆条目、查看详细内容，以及删除不需要的记忆。</p>
        </div>
        <button class="button primary" type="button" disabled>
          <Icon name="plus" />
          <span>添加记忆（敬请期待）</span>
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.memory-empty {
  min-height: 280px;
  display: grid;
  place-items: center;
}

.memory-empty-content {
  display: grid;
  gap: 16px;
  max-width: 420px;
  place-items: center;
  text-align: center;
}

.memory-empty-content strong {
  display: block;
  margin-bottom: 8px;
  color: var(--ink);
  font-size: 16px;
}

.memory-empty-content p {
  margin: 0;
  line-height: 1.6;
}

.memory-empty-icon {
  width: 48px;
  height: 48px;
  padding: 12px;
  border-radius: 8px;
  color: var(--primary);
  background: var(--primary-light);
}
</style>
