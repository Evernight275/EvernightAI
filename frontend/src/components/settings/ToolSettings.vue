<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { getIdentity, type AuthSession } from '../../api/auth';
import {
  listToolPolicies,
  resetToolPolicy,
  setToolPolicy,
  type ToolAccessMode,
  type ToolPermission,
  type ToolPolicySummary,
} from '../../api/tools';
import { authGeneration } from '../../runtime/workspaceRuntime';

const emit = defineEmits<{ changed: [] }>();
const policies = shallowRef<ToolPolicySummary[]>([]);
const drafts = ref<Record<string, ToolAccessMode>>({});
const identity = shallowRef<AuthSession | null>(null);
const loading = ref(false);
const busy = ref('');
const error = ref('');
const feedback = ref('');
const labels: Record<ToolAccessMode, string> = { allow: '允许', ask: '每次询问', deny: '禁止' };
const permissions: Record<ToolPermission, string> = {
  read: '读取',
  write: '写入',
  process: '运行进程',
  network: '联网',
  filesystem: '文件访问',
  shell: 'Shell',
  database: '数据库',
  external_api: '外部服务',
  destructive: '破坏性操作',
};
const canConfigure = computed(
  () =>
    identity.value?.authentication_enabled === false ||
    !!identity.value?.principal?.permissions.some(
      (permission) => permission === '*' || permission === 'tools:configure',
    ),
);
let controller = new AbortController();
let version = 0;
async function load(): Promise<void> {
  const current = ++version;
  controller.abort();
  controller = new AbortController();
  policies.value = [];
  drafts.value = {};
  identity.value = null;
  busy.value = '';
  loading.value = true;
  error.value = '';
  feedback.value = '';
  const results = await Promise.allSettled([
    listToolPolicies(controller.signal),
    getIdentity(undefined, controller.signal),
  ]);
  if (current !== version) return;
  const [list, auth] = results;
  if (list.status === 'fulfilled') {
    policies.value = list.value;
    drafts.value = Object.fromEntries(
      list.value.map((setting) => [setting.tool.name, setting.configured_mode ?? setting.mode]),
    );
  } else error.value = list.reason instanceof Error ? list.reason.message : '无法读取工具设置';
  if (auth.status === 'fulfilled') identity.value = auth.value;
  else error.value ||= auth.reason instanceof Error ? auth.reason.message : '无法读取当前账户权限';
  loading.value = false;
}
watch(authGeneration, () => void load(), { immediate: true, flush: 'sync' });
async function save(setting: ToolPolicySummary, reset = false): Promise<void> {
  if (busy.value || !canConfigure.value) return;
  const current = version;
  const name = setting.tool.name;
  busy.value = name;
  error.value = '';
  feedback.value = '';
  try {
    const saved = reset
      ? await resetToolPolicy(name, controller.signal)
      : await setToolPolicy(name, drafts.value[name]!, controller.signal);
    if (current !== version) return;
    policies.value = policies.value.map((item) => (item.tool.name === name ? saved : item));
    drafts.value[name] = saved.configured_mode ?? saved.mode;
    feedback.value = `${name} 已${reset ? '恢复默认设置' : '保存为“' + labels[saved.mode] + '”'}`;
    emit('changed');
  } catch (cause) {
    if (current === version && !controller.signal.aborted)
      error.value = cause instanceof Error ? cause.message : '保存失败，请重试';
  } finally {
    if (current === version) busy.value = '';
  }
}
onBeforeUnmount(() => {
  version++;
  controller.abort();
});
</script>
<template>
  <section
    class="settings-manager tool-settings"
    aria-label="工具权限管理"
    :aria-busy="loading || !!busy"
  >
    <div class="settings-row">
      <div>
        <h3>工具使用策略</h3>
        <p>
          {{
            identity?.authentication_enabled
              ? '设置对当前账户生效，刷新或重启后保留。'
              : '设置对本地工作区生效，刷新或重启后保留。'
          }}
        </p>
      </div>
      <button type="button" :disabled="loading || !!busy" @click="load">刷新工具</button>
    </div>
    <p class="settings-help">
      允许：直接执行；每次询问：批准后执行；禁止：从聊天可用工具中移除并阻止执行。
    </p>
    <p v-if="identity && !canConfigure" class="settings-help">
      当前账户可查看设置，修改需要 tools:configure 权限。
    </p>
    <p v-if="error" class="settings-feedback is-error" role="alert">{{ error }}</p>
    <p v-if="feedback" class="settings-feedback" role="status">{{ feedback }}</p>
    <p v-if="loading" class="settings-help" role="status">正在读取工具设置…</p>
    <p v-else-if="!policies.length && !error" class="settings-help">暂无已注册工具。</p>
    <form
      v-for="setting in policies"
      :key="setting.tool.name"
      class="settings-row tool-policy-row"
      :aria-label="setting.tool.name + ' 权限设置'"
      @submit.prevent="save(setting)"
    >
      <div class="tool-policy-description">
        <h3>
          {{ setting.tool.name }} <span class="settings-value">{{ labels[setting.mode] }}</span>
        </h3>
        <p>{{ setting.tool.description }}</p>
        <p>
          使用权限：{{
            setting.tool.permissions?.map((permission) => permissions[permission]).join('、') ||
            '无额外权限'
          }}
        </p>
        <p>
          默认：{{ labels[setting.default_mode] }} ·
          {{ setting.configured_mode === null ? '使用默认设置' : '已自定义' }}
        </p>
        <p v-if="setting.blocked_reason" class="settings-help">服务器规则禁止执行此工具。</p>
      </div>
      <div class="tool-policy-controls">
        <label
          >使用策略<select
            v-model="drafts[setting.tool.name]"
            :aria-label="setting.tool.name + ' 使用策略'"
            :disabled="!!busy || !canConfigure || !!setting.blocked_reason"
          >
            <option v-for="(label, value) in labels" :key="value" :value="value">
              {{ label }}
            </option>
          </select></label
        >
        <div class="settings-inline-actions">
          <button
            type="submit"
            :disabled="
              !!busy ||
              !canConfigure ||
              !!setting.blocked_reason ||
              drafts[setting.tool.name] === setting.configured_mode
            "
          >
            保存策略
          </button>
          <button
            type="button"
            :disabled="!!busy || !canConfigure || setting.configured_mode === null"
            @click="save(setting, true)"
          >
            恢复默认
          </button>
        </div>
      </div>
    </form>
  </section>
</template>
