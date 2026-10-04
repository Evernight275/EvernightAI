<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import {
  listSkills,
  listAgentRuns,
  getAgentRun,
  listAgentTrace,
  listAgentRunToolExecutions,
  pauseAgentRun,
  cancelAgentRun,
  resumeAgentRun,
  retryAgentRun,
  type AgentRunState,
  type SkillDefinition,
  type ToolApprovalDecision,
} from '../../api';
import { AgentRunSocketClient, type AgentTraceEvent } from '../../api';
import {
  canRetryRun,
  runSkillIssues,
  skillErrorIssues,
  type RunSkillIssue,
} from '../../domain/runSkills';
import { cancelForEditing, readRunDecisions, saveRunDecisions } from '../../runtime/runEditor';
import { authGeneration } from '../../runtime/workspaceRuntime';
import RunSkillConflict from '../skills/RunSkillConflict.vue';
import JsonCode from '../common/JsonCode.vue';
const emit = defineEmits<{ changed: [] }>();
const props = defineProps<{ active?: boolean }>();
const runs = ref<AgentRunState[]>([]);
const selected = ref<AgentRunState | null>(null);
const details = ref<unknown>(null);
const busy = ref(false);
const error = ref('');
const decisions = ref<Record<string, 'approved' | 'denied'>>({});
const confirm = ref<'pause' | 'cancel' | 'retry' | 'resume' | null>(null);
const live = ref(false);
const connection = ref('未连接');
const events = ref<AgentTraceEvent[]>([]);
const skills = ref<SkillDefinition[] | null>(null);
const conflictErrors = ref<RunSkillIssue[]>([]);
const issues = computed(() =>
  conflictErrors.value.length ? conflictErrors.value : runSkillIssues(selected.value, skills.value),
);
const lifetime = new AbortController();
let identity = new AbortController();
let mounted = true;
let socket: AgentRunSocketClient | null = null;
function stopLive() {
  socket?.close();
  socket = null;
  live.value = false;
}
function startLive() {
  if (!selected.value) return;
  stopLive();
  events.value = [];
  live.value = true;
  socket = new AgentRunSocketClient({
    onStatus: (status) => {
      connection.value = { connecting: '连接中', connected: '已连接', disconnected: '连接已断开' }[
        status
      ];
    },
    onError: (cause) => {
      error.value = cause.error_message;
    },
    onTrace: (id, event) => {
      if (id !== selected.value?.run_id) return;
      events.value = [...events.value, event].slice(-200);
      if (['run_stopped', 'run_paused'].includes(event.event_type) && !busy.value)
        void perform(() => inspect(id, false));
    },
  });
  socket.subscribeRun(selected.value.run_id);
  socket.connect();
}
onUnmounted(() => {
  mounted = false;
  lifetime.abort();
  stopLive();
});
watch(
  () => props.active,
  (active) => {
    if (active === false) stopLive();
  },
);
watch(
  authGeneration,
  () => {
    identity.abort();
    identity = new AbortController();
    stopLive();
    selected.value = null;
    runs.value = [];
    decisions.value = {};
    details.value = null;
    confirm.value = null;
    conflictErrors.value = [];
    skills.value = null;
    error.value = '';
  },
  { flush: 'sync' },
);
watch(
  [selected, decisions],
  ([run, choices]) => {
    if (run) saveRunDecisions(run, choices);
  },
  { deep: true },
);
async function perform(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true;
  error.value = '';
  const generation = authGeneration.value;
  try {
    await action();
  } catch (cause) {
    if (mounted && generation === authGeneration.value) {
      error.value = cause instanceof Error ? cause.message : '操作失败';
      const conflict = skillErrorIssues(cause, selected.value);
      if (conflict.length) conflictErrors.value = conflict;
    }
  } finally {
    busy.value = false;
  }
}
async function load() {
  const generation = authGeneration.value;
  const loaded = await listAgentRuns(lifetime.signal);
  if (!mounted || generation !== authGeneration.value) return;
  runs.value = loaded;
  if (selected.value) await inspect(selected.value.run_id);
}
async function inspect(id: string, stop = true) {
  if (stop) stopLive();
  const generation = authGeneration.value;
  const previous = selected.value?.run_id === id ? decisions.value : {};
  const [run, catalog] = await Promise.all([
    getAgentRun(id, lifetime.signal),
    listSkills(lifetime.signal).catch(() => null),
  ]);
  if (!mounted || generation !== authGeneration.value) return;
  if (selected.value?.run_id !== id) conflictErrors.value = [];
  decisions.value = Object.fromEntries(
    (run.pending_approval_requests || []).flatMap((item) => {
      const status = previous[item.approval_id] || readRunDecisions(run)[item.approval_id];
      return status ? [[item.approval_id, status]] : [];
    }),
  );
  selected.value = run;
  skills.value = catalog;
  confirm.value = null;
  details.value = null;
}
async function editRun() {
  if (!selected.value) return;
  const id = selected.value.run_id;
  const generation = authGeneration.value;
  await perform(async () => {
    const run = await cancelForEditing(id, AbortSignal.any([lifetime.signal, identity.signal]));
    if (!mounted || generation !== authGeneration.value) return;
    selected.value = run;
    window.location.assign(`/chat.html?run=${encodeURIComponent(id)}&edit=1`);
  });
}
async function control() {
  if (!selected.value || !confirm.value) return;
  const id = selected.value.run_id;
  const action = confirm.value;
  if ((action === 'resume' || action === 'retry') && issues.value.length) return;
  if (action === 'retry' && !canRetryRun(selected.value)) return;
  const generation = authGeneration.value;
  await perform(async () => {
    let updated: AgentRunState;
    if (action === 'pause') updated = await pauseAgentRun(id);
    else if (action === 'cancel') updated = await cancelAgentRun(id);
    else if (action === 'retry') updated = await retryAgentRun(id);
    else {
      const approvals = selected.value?.pending_approval_requests || [];
      if (approvals.some((item) => !decisions.value[item.approval_id]))
        throw new Error('请逐项批准或拒绝所有待审批工具');
      const choices: ToolApprovalDecision[] = approvals.map((item) => ({
        approval_id: item.approval_id,
        tool_call_id: item.tool_call_id,
        status: decisions.value[item.approval_id]!,
      }));
      updated = await resumeAgentRun(id, { approvals: choices });
    }
    if (!mounted || generation !== authGeneration.value) return;
    selected.value = updated;
    confirm.value = null;
    decisions.value = {};
    emit('changed');
    await load();
  });
}
onMounted(() => perform(load));
</script>
<template>
  <section class="settings-manager" aria-label="运行管理">
    <div class="settings-toolbar">
      <button :disabled="busy" @click="perform(load)">刷新运行记录</button>
    </div>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="busy" role="status">正在处理…</p>
    <div v-for="run in runs" :key="run.run_id" class="settings-row">
      <div>
        <h3>{{ run.request.model_id }} · {{ run.status }}</h3>
        <p>{{ run.run_id }}</p>
      </div>
      <button :disabled="busy" @click="perform(() => inspect(run.run_id))">管理运行</button>
    </div>
    <section v-if="selected" class="settings-form">
      <h3>{{ selected.run_id }} · {{ selected.status }}</h3>
      <RunSkillConflict :issues="issues" :run="selected" :busy="busy" @edit="editRun" />
      <div class="settings-inline-actions">
        <button v-if="!live" :disabled="busy" @click="startLive">实时轨迹</button
        ><button v-else @click="stopLive">停止订阅</button>
        <button :disabled="busy" @click="perform(() => inspect(selected!.run_id))">刷新详情</button>
        <button
          :disabled="busy"
          @click="
            perform(async () => {
              details = await listAgentTrace(selected!.run_id);
            })
          "
        >
          执行轨迹
        </button>
        <button
          :disabled="busy"
          @click="
            perform(async () => {
              details = await listAgentRunToolExecutions(selected!.run_id);
            })
          "
        >
          工具执行记录
        </button>
        <button :disabled="busy || selected.status !== 'running'" @click="confirm = 'pause'">
          暂停运行
        </button>
        <button
          :disabled="busy || !['running', 'paused'].includes(selected.status || '')"
          @click="confirm = 'cancel'"
        >
          取消运行
        </button>
        <button
          :disabled="busy || issues.length > 0 || !canRetryRun(selected)"
          @click="confirm = 'retry'"
        >
          重试运行
        </button>
      </div>
      <div v-if="live" aria-label="实时执行轨迹">
        <p role="status">{{ connection }}</p>
        <p v-for="(event, index) in events" :key="index">
          {{ event.event_type }} · {{ event.summary || event.text_delta || event.error_message }}
        </p>
      </div>
      <div
        v-for="approval in selected.pending_approval_requests"
        :key="approval.approval_id"
        class="settings-confirm"
      >
        <h4>{{ approval.tool_name }}</h4>
        <p>{{ approval.permissions?.join('、') }} · {{ approval.safety_level }}</p>
        <pre><JsonCode :source="JSON.stringify(approval.tool_call, null, 2)" /></pre>
        <label
          >审批决定<select
            v-model="decisions[approval.approval_id]"
            :disabled="busy || issues.length > 0"
          >
            <option value="" disabled>请选择</option>
            <option value="approved">批准</option>
            <option value="denied">拒绝</option>
          </select></label
        >
      </div>
      <button
        v-if="selected.status === 'paused'"
        :disabled="
          busy ||
          issues.length > 0 ||
          canRetryRun(selected) ||
          selected.pending_approval_requests?.some((item) => !decisions[item.approval_id])
        "
        @click="confirm = 'resume'"
      >
        继续运行
      </button>
      <div v-if="confirm" class="settings-confirm">
        <p>
          确认{{ { pause: '暂停', cancel: '取消', retry: '重试', resume: '继续' }[confirm] }}运行
          {{ selected.run_id }}？
        </p>
        <button :disabled="busy" @click="confirm = null">返回</button
        ><button :disabled="busy" @click="control">确认操作</button>
      </div>
      <pre
        v-if="details"
        class="settings-result"
      ><JsonCode :source="JSON.stringify(details, null, 2)" /></pre>
    </section>
  </section>
</template>
