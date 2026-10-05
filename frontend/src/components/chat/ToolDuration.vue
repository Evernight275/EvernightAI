<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { toolElapsed } from './toolTiming';
const props = defineProps<{
  startedAt?: string;
  finishedAt?: string;
  durationMs?: number;
  running?: boolean;
}>();
const now = ref(Date.now());
let timer: ReturnType<typeof setInterval> | undefined;
onMounted(() => {
  watch(
    () => props.running,
    (running) => {
      clearInterval(timer);
      now.value = Date.now();
      timer = running
        ? setInterval(() => {
            now.value = Date.now();
          }, 1000)
        : undefined;
    },
    { immediate: true },
  );
});
onUnmounted(() => clearInterval(timer));
const label = computed(() => toolElapsed(props, now.value));
</script>

<template>
  <span v-if="label" class="tool-duration" :aria-label="'执行耗时 ' + label">{{ label }}</span>
</template>
<style scoped>
.tool-duration {
  flex-shrink: 0;
  color: var(--color-text-muted);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}
</style>
