<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { parameterFields, parseSkillVariables } from '../../domain/skillParameters'
const props = defineProps<{ modelValue: string; schema?: Record<string, unknown> | null; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const fields = computed(() => parameterFields(props.schema))
const mode = ref<'form' | 'json'>('form')
const parsed = computed(() => { try { return parseSkillVariables(props.modelValue) } catch { return null } })
const useForm = computed(() => mode.value === 'form' && fields.value !== null && parsed.value !== null
  && Object.keys(parsed.value).every(name => fields.value?.some(field => field.name === name)))
watch(() => props.schema, () => { mode.value = 'form' })
watch([fields, useForm], () => {
  if (!useForm.value || props.disabled) return
  const requiredBooleans = fields.value?.filter(field => field.required && field.type === 'boolean' && !Object.hasOwn(parsed.value!, field.name)) || []
  if (requiredBooleans.length) {
    const values = Object.assign(Object.create(null), parsed.value)
    for (const field of requiredBooleans) values[field.name] = false
    emit('update:modelValue', JSON.stringify(values, null, 2))
  }
}, { immediate: true })
function set(name: string, value: unknown) {
  const variables = Object.assign(Object.create(null), parsed.value || {}) as Record<string, unknown>
  if (value === undefined) delete variables[name]
  else variables[name] = value
  emit('update:modelValue', JSON.stringify(variables, null, 2))
}
function text(event: Event) { return (event.target as HTMLInputElement).value }
function numeric(event: Event) {
  const value = text(event)
  return value === '' ? undefined : Number(value)
}
</script>

<template>
  <div class="skill-variables settings-form">
    <div v-if="fields" class="skill-parameter-modes" role="group" aria-label="参数编辑模式">
      <button type="button" :disabled="disabled || !parsed" :aria-pressed="useForm" @click="mode = 'form'">表单</button>
      <button type="button" :disabled="disabled" :aria-pressed="!useForm" @click="mode = 'json'">JSON</button>
    </div>
    <fieldset v-if="useForm" :disabled="disabled">
      <div v-for="field in fields" :key="field.name" class="skill-parameter">
        <label v-if="!field.required" class="settings-checkbox"><input type="checkbox" :checked="Object.hasOwn(parsed!, field.name)"
          @change="set(field.name, ($event.target as HTMLInputElement).checked ? (field.type === 'boolean' ? false : field.type === 'string' ? '' : 0) : undefined)" />{{ field.schema.title || field.name }}</label>
        <label v-if="field.required || Object.hasOwn(parsed!, field.name)">
          <span>{{ field.schema.title || field.name }}{{ field.required ? ' *' : '' }}</span>
          <select v-if="Array.isArray(field.schema.enum)" :aria-label="`${field.schema.title || field.name}${field.required ? ' *' : ''}`" :value="JSON.stringify(parsed![field.name])" :required="field.required" @change="set(field.name, JSON.parse(text($event)))">
            <option disabled value="">请选择</option><option v-for="value in field.schema.enum" :key="JSON.stringify(value)" :value="JSON.stringify(value)">{{ String(value) }}</option>
          </select>
          <input v-else-if="field.type === 'boolean'" type="checkbox" :checked="parsed![field.name] === true" @change="set(field.name, ($event.target as HTMLInputElement).checked)" />
          <input v-else-if="field.type === 'integer' || field.type === 'number'" type="number" :value="parsed![field.name]" :required="field.required"
            :min="field.schema.minimum as number | undefined" :max="field.schema.maximum as number | undefined" :step="field.type === 'integer' ? 1 : 'any'" @input="set(field.name, numeric($event))" />
          <input v-else type="text" :value="parsed![field.name]" :required="field.required" :minlength="field.schema.minLength as number | undefined"
            :maxlength="field.schema.maxLength as number | undefined" @input="set(field.name, text($event))" />
        </label>
        <p v-if="field.schema.description" class="settings-help">{{ field.schema.description }}</p>
      </div>
      <p v-if="!fields?.length" class="settings-help">无参数</p>
    </fieldset>
    <label v-else>技能参数（JSON）<textarea :value="modelValue" :disabled="disabled" rows="5" @input="emit('update:modelValue', text($event))" /></label>
  </div>
</template>

<style scoped>
.skill-parameter-modes { display: inline-flex; gap: 4px; margin-bottom: 12px; }
.skill-parameter-modes button { border-radius: 4px; padding: 5px 12px; }
.skill-parameter-modes button[aria-pressed='true'] { background: var(--color-border); }
.skill-parameter { min-width: 0; overflow-wrap: anywhere; }
.skill-parameter input[type='checkbox'] { width: auto; justify-self: start; }
</style>
