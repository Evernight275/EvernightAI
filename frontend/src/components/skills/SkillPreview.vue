<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue';
import { renderSkill, type RenderedSkill, type SkillDefinition } from '../../api/skills';
import { parseSkillVariables } from '../../domain/skillParameters';
const props = defineProps<{ skill: SkillDefinition; variables: string; disabled?: boolean }>();
const result = ref<RenderedSkill | null>(null);
const error = ref('');
const busy = ref(false);
let generation = 0;
watch([() => props.skill, () => props.variables], () => {
  generation++;
  result.value = null;
  error.value = '';
  busy.value = false;
});
onUnmounted(() => generation++);
async function preview() {
  if (busy.value || props.disabled || props.skill.is_enabled === false) return;
  const current = ++generation;
  busy.value = true;
  error.value = '';
  result.value = null;
  try {
    const rendered = await renderSkill(props.skill.name, {
      variables: parseSkillVariables(props.variables),
    });
    if (current === generation) result.value = rendered;
  } catch (cause) {
    if (current === generation)
      error.value = cause instanceof Error ? cause.message : '技能预览失败';
  } finally {
    if (current === generation) busy.value = false;
  }
}
</script>

<template>
  <section class="skill-preview" aria-label="技能提示词预览">
    <button
      type="button"
      :disabled="disabled || busy || skill.is_enabled === false"
      @click="preview"
    >
      {{ busy ? '正在预览…' : '预览技能提示词' }}
    </button>
    <p v-if="error" role="alert">{{ error }}</p>
    <div v-if="result" class="skill-preview-result">
      <div v-for="(message, index) in result.messages" :key="index">
        <strong>{{ message.role }}</strong>
        <pre v-for="(part, partIndex) in message.content" :key="partIndex">{{ part.text }}</pre>
      </div>
      <p v-if="!result.messages?.length">无提示词消息</p>
    </div>
  </section>
</template>

<style scoped>
.skill-preview {
  padding: 12px 0;
}
.skill-preview button {
  padding: 7px 16px;
  border-radius: 20px;
}
.skill-preview-result {
  margin-top: 12px;
  max-height: 300px;
  overflow: auto;
  font-size: 13px;
}
.skill-preview-result pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
