<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { managementActions } from './managementActions'
import { chatActor } from '../../state/chatMachine'
import type { Session } from '../../api'
const emit = defineEmits<{ changed: [] }>()
const selected = ref(managementActions[0]!.id)
const action = computed(() => managementActions.find(item => item.id === selected.value)!)
const groups = [...new Set(managementActions.map(item => item.group))]
const values = ref<Record<string, string>>({})
const busy = ref(false)
const error = ref('')
const result = ref<unknown>(undefined)
const confirmation = ref(false)
watch(action, next => { values.value = Object.fromEntries(next.fields.map(field => [field.key, field.value || ''])); result.value = undefined; error.value = ''; confirmation.value = false }, { immediate: true })
async function execute() {
  busy.value = true; error.value = ''; result.value = undefined
  try {
    result.value = await action.value.run({ ...values.value }) ?? { message: '操作完成' }
    if (['rename', 'restore', 'archive'].includes(action.value.id)) chatActor.send({ type: 'SESSION_UPDATED', session: result.value as Session })
    emit('changed')
  }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '操作失败' }
  finally { busy.value = false; confirmation.value = false }
}
</script>
<template>
  <section class="settings-manager" aria-label="工作区资源管理">
    <p class="settings-help">查询资源、分析数据和排查运行问题。高级参数支持后端定义的过滤条件和字段。</p>
    <form class="settings-form" @submit.prevent="action.confirmation ? confirmation = true : execute()">
      <fieldset :disabled="busy || confirmation">
        <label>操作<select v-model="selected" aria-label="操作"><optgroup v-for="group in groups" :key="group" :label="group"><option v-for="item in managementActions.filter(item => item.group === group)" :key="item.id" :value="item.id">{{ item.label }}</option></optgroup></select></label>
        <label v-for="field in action.fields" :key="`${selected}-${field.key}`">{{ field.label }}
          <textarea v-if="field.json" v-model="values[field.key]" rows="7" required spellcheck="false" />
          <input v-else v-model="values[field.key]" :required="!field.optional" />
        </label>
        <button class="button-primary">{{ busy ? '正在处理…' : action.label }}</button>
      </fieldset>
    </form>
    <div v-if="confirmation" class="settings-confirm" role="group" aria-label="操作确认"><p>{{ action.confirmation }}</p><button :disabled="busy" @click="confirmation = false">取消</button><button :disabled="busy" @click="execute">确认执行</button></div>
    <p v-if="error" role="alert">{{ error }}</p>
    <div v-if="result !== undefined" class="settings-result" role="region" aria-label="操作结果"><pre>{{ JSON.stringify(result, null, 2) }}</pre></div>
  </section>
</template>
