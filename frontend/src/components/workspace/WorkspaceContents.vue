<script setup lang="ts">
import type { WorkspaceSnapshot } from '../../domain/workspace'
import CapabilityCatalogView from '../capabilities/CapabilityCatalogView.vue'
import ConversationIndexView from '../conversations/ConversationIndexView.vue'
import ExecutionIndexView from '../executions/ExecutionIndexView.vue'
import KnowledgeIndexView from '../knowledge/KnowledgeIndexView.vue'
import ProviderCatalogView from '../providers/ProviderCatalogView.vue'

defineProps<{
  workspace: WorkspaceSnapshot
}>()
</script>

<template>
  <ProviderCatalogView :catalog="workspace.providerCatalog" />
  <ConversationIndexView :index="workspace.conversationIndex" />
  <KnowledgeIndexView :index="workspace.knowledgeIndex" />
  <CapabilityCatalogView :catalog="workspace.capabilityCatalog" />
  <ExecutionIndexView :index="workspace.executionIndex" />
</template>
