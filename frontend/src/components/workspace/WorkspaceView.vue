<script setup lang="ts">
import { computed, onUnmounted, ref, shallowRef } from 'vue';
import { Activity, Brain, Database, Plug, Settings2, Sparkles, Wrench, X } from '@lucide/vue';
import { authGeneration } from '../../runtime/workspaceRuntime';
import { workspaceActor } from '../../state/workspaceMachine';
import ApiKeyManager from '../settings/ApiKeyManager.vue';
import AccountSettings from '../settings/AccountSettings.vue';
import WorkspaceContents from './WorkspaceContents.vue';
import WorkspaceIssues from './WorkspaceIssues.vue';
import WorkspaceStatus from './WorkspaceStatus.vue';
import ProviderSettings from '../settings/ProviderSettings.vue';
import MemorySettings from '../settings/MemorySettings.vue';
import ResourceSettings from '../settings/ResourceSettings.vue';
import RunSettings from '../settings/RunSettings.vue';
import SkillSettings from '../settings/SkillSettings.vue';
import ToolSettings from '../settings/ToolSettings.vue';

defineProps<{ embedded?: boolean; active?: boolean }>();
defineEmits<{ close: [] }>();
const snapshot = shallowRef(workspaceActor.getSnapshot());
const subscription = workspaceActor.subscribe((next) => {
  snapshot.value = next;
});
onUnmounted(() => subscription.unsubscribe());
const state = computed(() => String(snapshot.value.value));
const context = computed(() => snapshot.value.context);
const activeSection = ref('general');
const groups = [
  { label: '', sections: [{ id: 'general', label: '常规', icon: Settings2 }] },
  {
    label: '模型与能力',
    sections: [
      { id: 'connections', label: '连接与认证', icon: Plug },
      { id: 'tools', label: '工具管理', icon: Wrench },
      { id: 'skills', label: '技能管理', icon: Sparkles },
      { id: 'memories', label: '记忆管理', icon: Brain },
    ],
  },
  {
    label: '运行与数据',
    sections: [
      { id: 'runs', label: '运行管理', icon: Activity },
      { id: 'resources', label: '工作区资源', icon: Database },
    ],
  },
];
const sections = groups.flatMap((group) => group.sections);
// What the workspace currently holds; each entry opens the section that manages it.
const overview = computed(() => {
  const workspace = context.value.workspace;
  const providers = workspace.providerCatalog.providers.filter(
    (provider) => provider.is_enabled !== false,
  );
  const models = workspace.providerCatalog.modelGroups
    .filter((group) => group.provider.is_enabled !== false)
    .reduce((count, group) => count + group.models.length, 0);
  return [
    {
      section: 'connections',
      label: '模型服务',
      value: providers.length,
      note: `${models} 个模型`,
    },
    { section: 'tools', label: '工具', value: workspace.capabilityCatalog.tools.length },
    { section: 'skills', label: '技能', value: workspace.capabilityCatalog.skills.length },
    { section: 'memories', label: '记忆', value: workspace.knowledgeIndex.memories.length },
    { section: 'runs', label: '运行记录', value: workspace.executionIndex.runs.length },
  ];
});
function refresh(): void {
  workspaceActor.send({ type: 'REFRESH' });
}
</script>

<template>
  <div class="settings-page-frame">
    <section class="settings-shell" aria-label="设置">
      <header class="settings-titlebar">
        <h1>设置</h1>
        <button
          v-if="embedded"
          type="button"
          class="settings-close"
          aria-label="关闭设置"
          @click="$emit('close')"
        >
          <X :size="20" aria-hidden="true" />
        </button>
        <a v-else class="settings-close" href="/chat.html" aria-label="返回聊天"
          ><X :size="20" aria-hidden="true"
        /></a>
      </header>
      <nav class="settings-nav" aria-label="设置分类">
        <template v-for="group in groups" :key="group.label">
          <p v-if="group.label" class="settings-nav-label">{{ group.label }}</p>
          <button
            v-for="section in group.sections"
            :key="section.id"
            type="button"
            :aria-current="activeSection === section.id ? 'page' : undefined"
            @click="activeSection = section.id"
          >
            <component :is="section.icon" :size="18" aria-hidden="true" /><span>{{
              section.label
            }}</span>
          </button>
        </template>
      </nav>
      <div class="settings-content" :key="activeSection">
        <h2 class="settings-section-title">
          {{ sections.find((section) => section.id === activeSection)?.label }}
        </h2>
        <template v-if="activeSection === 'general'">
          <WorkspaceStatus
            :state="state"
            :loaded-at="context.workspace.loadedAt"
            :connection-error="context.connectionError"
            @refresh="refresh"
          />
          <WorkspaceIssues :issues="context.issues" />
          <ul class="settings-overview" aria-label="工作区概览">
            <li v-for="item in overview" :key="item.section">
              <button type="button" @click="activeSection = item.section">
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
                <small v-if="item.note">{{ item.note }}</small>
              </button>
            </li>
          </ul>
          <div class="settings-row">
            <div>
              <h3>聊天记录</h3>
              <p>会话保存在 EvernightAI 服务端，可在聊天侧栏中逐个删除。</p>
            </div>
          </div>
          <div class="settings-row">
            <div>
              <h3>账号</h3>
              <p>登录状态保存在此浏览器的本地存储中，退出登录不会删除服务端的聊天记录。</p>
            </div>
            <button type="button" @click="activeSection = 'connections'">管理账号</button>
          </div>
        </template>
        <template v-else-if="activeSection === 'connections'">
          <AccountSettings :key="authGeneration" />
          <ApiKeyManager :key="authGeneration" />
          <ProviderSettings
            :key="authGeneration"
            :catalog="context.workspace.providerCatalog"
            @changed="refresh"
          />
          <div class="settings-row">
            <div>
              <h3>可用模型</h3>
              <p>
                {{
                  context.workspace.providerCatalog.providers.filter(
                    (provider) => provider.is_enabled !== false,
                  ).length
                }}
                个服务 ·
                {{
                  context.workspace.providerCatalog.modelGroups
                    .filter((group) => group.provider.is_enabled !== false)
                    .reduce((count, group) => count + group.models.length, 0)
                }}
                个模型
              </p>
            </div>
            <button type="button" :disabled="state === 'loading'" @click="refresh">刷新</button>
          </div>
          <details class="settings-resource-details" v-if="context.workspace.loadedAt">
            <summary>查看工作区资源</summary>
            <WorkspaceContents :workspace="context.workspace" />
          </details>
        </template>
        <MemorySettings
          :key="authGeneration"
          v-else-if="activeSection === 'memories'"
          @changed="refresh"
        />
        <ToolSettings
          :key="authGeneration"
          v-else-if="activeSection === 'tools'"
          @changed="refresh"
        />
        <SkillSettings
          :key="authGeneration"
          v-else-if="activeSection === 'skills'"
          :skills="context.workspace.capabilityCatalog.skills"
          :tools="context.workspace.capabilityCatalog.tools"
          @changed="refresh"
        />
        <ResourceSettings
          :key="authGeneration"
          v-else-if="activeSection === 'resources'"
          @changed="refresh"
        />
        <RunSettings
          :key="authGeneration"
          v-else-if="activeSection === 'runs'"
          :active="active !== false"
          @changed="refresh"
        />
      </div>
    </section>
  </div>
</template>
