<script setup lang="ts">
import { computed } from 'vue'
import type { ProviderInfo, ProviderModelGroup } from '../api'
import Icon from '../components/Icon.vue'

const props = defineProps<{
  providers: ProviderInfo[]
  providerModelGroups: ProviderModelGroup[]
  selectedModelLabel: string
  loading: boolean
  error: string | null
  updatedAt: string
}>()

const selectedProviderModel = defineModel<string>('selectedProviderModel', { required: true })

const emit = defineEmits<{
  refresh: []
}>()

const enabledProviderCount = computed(() => (
  props.providers.filter((provider) => provider.is_enabled !== false).length
))
const providerModelCount = computed(() => (
  props.providerModelGroups.reduce((total, group) => total + group.models.length, 0)
))
</script>

<template>
  <section class="provider-config" aria-label="模型提供商配置">
    <div class="panel-head">
      <h2><Icon name="table-2" /><span>模型提供商配置</span></h2>
      <div class="panel-head-actions">
        <span>{{ enabledProviderCount }}/{{ providers.length }} 个 provider · {{ providerModelCount }} 个模型</span>
        <button
          class="button compact-button primary"
          :class="{ 'is-spinning': loading }"
          type="button"
          :disabled="loading"
          @click="emit('refresh')"
        >
          <Icon name="activity" />
          <span>{{ loading ? '拉取中' : '刷新模型' }}</span>
        </button>
      </div>
    </div>
    <div class="provider-summary">
      <span>当前聊天模型：{{ selectedModelLabel }}</span>
      <span>{{ updatedAt ? `最近刷新：${updatedAt}` : '等待刷新' }}</span>
    </div>
    <p v-if="error" class="provider-error">{{ error }}</p>
    <div v-if="providers.length === 0" class="provider-empty">
      <Icon name="inbox" class="empty-state-icon" />
      <div class="empty-state-text">
        <strong>暂无模型提供商</strong>
        <span>请检查后端配置，确保至少有一个模型提供商已启用</span>
      </div>
    </div>
    <div v-else class="provider-list">
      <article
        v-for="group in providerModelGroups"
        :key="group.provider.provider_id"
        class="provider-row"
      >
        <div class="provider-row-main">
          <div>
            <h3>{{ group.provider.name }}</h3>
            <p>{{ group.provider.provider_id }} · {{ group.provider.type }}</p>
          </div>
          <span class="tag">{{ group.provider.is_enabled === false ? '停用' : '启用' }}</span>
        </div>
        <div class="provider-models">
          <span v-if="group.models.length === 0" class="provider-model-empty">
            未发现模型
          </span>
          <button
            v-for="model in group.models"
            v-else
            :key="model.model_id"
            class="model-chip"
            :class="{ 'is-selected': selectedProviderModel === `${group.provider.provider_id}::${model.model_id}` }"
            type="button"
            @click="selectedProviderModel = `${group.provider.provider_id}::${model.model_id}`"
          >
            {{ model.model_id }}
          </button>
        </div>
      </article>
    </div>
  </section>
</template>
