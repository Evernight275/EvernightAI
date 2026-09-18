<script setup lang="ts">
import { Check, ChevronDown, Search, X } from '@lucide/vue'
import { computed, ref } from 'vue'
import type { ProviderCatalog } from '../../domain/workspace'
import { useDialog } from '../common/dialog'

const props = defineProps<{
  catalog: ProviderCatalog
  providerId: string
  modelId: string
  disabled: boolean
}>()
const emit = defineEmits<{ select: [providerId: string, modelId: string] }>()
const open = ref(false)
const search = ref('')
const close = (): void => { open.value = false }
const { setDialog, onCancel, onBackdropClick, onKeydown } = useDialog(() => open.value, close)
const groups = computed(() => props.catalog.modelGroups.map((group) => ({
  ...group,
  models: group.models.filter((model) => `${group.provider.name} ${model.model_id}`
    .toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase())),
})).filter((group) => group.models.length))
function choose(providerId: string, modelId: string): void {
  if (props.disabled) return
  emit('select', providerId, modelId)
  close()
}
</script>

<template>
  <button class="chat-model-trigger" type="button" :disabled="disabled" aria-label="选择模型"
    aria-haspopup="dialog" :aria-expanded="open" @click="search = ''; open = true">
    <span>{{ modelId || '选择模型' }}</span><ChevronDown :size="14" aria-hidden="true" />
  </button>
  <dialog :ref="setDialog" class="chat-model-dialog" aria-labelledby="chat-model-title"
    @cancel="onCancel" @click="onBackdropClick" @keydown="onKeydown">
    <header><h2 id="chat-model-title">选择模型</h2>
      <button class="icon-button" type="button" aria-label="关闭模型选择" @click="close"><X :size="17" /></button>
    </header>
    <label class="chat-model-search"><Search :size="17" aria-hidden="true" />
      <input v-model="search" type="search" aria-label="搜索模型" placeholder="搜索模型或服务" autofocus />
    </label>
    <div class="chat-model-list">
      <section v-for="group in groups" :key="group.provider.provider_id" :aria-label="group.provider.name">
        <h3>{{ group.provider.name }}</h3>
        <button v-for="model in group.models" :key="model.model_id" type="button" :disabled="disabled"
          :aria-pressed="providerId === group.provider.provider_id && modelId === model.model_id"
          @click="choose(group.provider.provider_id, model.model_id)">
          <span>{{ model.model_id }}</span>
          <Check v-if="providerId === group.provider.provider_id && modelId === model.model_id" :size="16" aria-hidden="true" />
        </button>
      </section>
      <p v-if="!groups.length">没有匹配的模型</p>
    </div>
  </dialog>
</template>
