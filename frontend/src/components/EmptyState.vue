<script setup lang="ts">
import Icon from './Icon.vue'

defineProps<{
  icon: string
  title: string
  description?: string
  actionLabel?: string
}>()

const emit = defineEmits<{
  action: []
}>()
</script>

<template>
  <div class="empty-state">
    <Icon :name="icon" class="empty-state-icon" />
    <div class="empty-state-text">
      <strong>{{ title }}</strong>
      <span v-if="description">{{ description }}</span>
    </div>
    <button v-if="actionLabel" class="button primary" @click="emit('action')">
      {{ actionLabel }}
    </button>
  </div>
</template>

<style scoped>
.empty-state {
  min-height: 240px;
  display: grid;
  gap: 16px;
  place-items: center;
  align-content: center;
  padding: 40px 20px;
}
</style>
