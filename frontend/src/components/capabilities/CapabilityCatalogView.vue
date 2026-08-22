<script setup lang="ts">
import type { CapabilityCatalog } from '../../domain/workspace'
import EmptyValue from '../common/EmptyValue.vue'

defineProps<{
  catalog: CapabilityCatalog
}>()
</script>

<template>
  <section>
    <h2>能力目录</h2>

    <h3>工具（{{ catalog.tools.length }}）</h3>
    <EmptyValue v-if="!catalog.tools.length" label="没有工具" />
    <ul v-else>
      <li v-for="tool in catalog.tools" :key="tool.name">
        <strong>{{ tool.name }}</strong>：{{ tool.description }}
        <span> / {{ tool.safety_level || 'safe' }}</span>
        <span v-if="tool.requires_approval"> / 需要审批</span>
      </li>
    </ul>

    <h3>技能（{{ catalog.skills.length }}）</h3>
    <EmptyValue v-if="!catalog.skills.length" label="没有技能" />
    <ul v-else>
      <li v-for="skill in catalog.skills" :key="skill.name">
        <strong>{{ skill.name }}</strong>：{{ skill.description }}
        <span v-if="skill.capabilities?.length">
          / {{ skill.capabilities.join(', ') }}
        </span>
      </li>
    </ul>

    <h3>数据源（{{ catalog.dataSources.length }}）</h3>
    <EmptyValue v-if="!catalog.dataSources.length" label="没有数据源" />
    <ul v-else>
      <li v-for="source in catalog.dataSources" :key="source.source_id">
        <strong>{{ source.name }}</strong> / {{ source.source_id }}
        <span> / 字段 {{ source.fields?.length || 0 }}</span>
        <span> / 指标 {{ source.metrics?.length || 0 }}</span>
        <p v-if="source.description">{{ source.description }}</p>
      </li>
    </ul>
  </section>
</template>
