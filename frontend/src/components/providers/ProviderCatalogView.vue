<script setup lang="ts">
import type { ProviderCatalog } from '../../domain/workspace'
import EmptyValue from '../common/EmptyValue.vue'

const props = defineProps<{
  catalog: ProviderCatalog
}>()

function modelsFor(providerId: string) {
  return props.catalog.modelGroups.find(
    (group) => group.provider.provider_id === providerId,
  )?.models || []
}
</script>

<template>
  <section class="settings-resource-section">
    <h2>模型目录（{{ catalog.providers.length }}）</h2>
    <EmptyValue v-if="!catalog.providers.length" label="没有 Provider" />
    <ul v-else>
      <li v-for="provider in catalog.providers" :key="provider.provider_id">
        <strong>{{ provider.name }}</strong>
        <span> / {{ provider.provider_id }} / {{ provider.type }}</span>
        <span> / {{ provider.is_enabled === false ? '停用' : '启用' }}</span>
        <ul v-if="modelsFor(provider.provider_id).length">
          <li
            v-for="model in modelsFor(provider.provider_id)"
            :key="model.model_id"
          >
            {{ model.model_id }}
            <span v-if="model.capabilities?.length">
              （{{ model.capabilities.join(', ') }}）
            </span>
          </li>
        </ul>
        <EmptyValue v-else label="没有模型" />
      </li>
    </ul>
  </section>
</template>
