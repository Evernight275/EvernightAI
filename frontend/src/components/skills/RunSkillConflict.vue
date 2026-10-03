<script setup lang="ts">
import { computed, ref } from 'vue';
import { Pencil } from '@lucide/vue';
import type { AgentRunState } from '../../api';
import { skillIssueText, type RunSkillIssue } from '../../domain/runSkills';
import { useDialog } from '../common/dialog';

const props = defineProps<{ issues: RunSkillIssue[]; run: AgentRunState | null; busy?: boolean }>();
const emit = defineEmits<{ edit: [] }>();
const confirming = ref(false);
const active = computed(() => ['running', 'paused'].includes(props.run?.status || ''));
const completed = computed(() => [
  ...new Set(
    (props.run?.trace || [])
      .filter((event) => event.event_type === 'tool_completed')
      .map((event) => event.tool_call?.tool_call?.name || '工具'),
  ),
]);
const { setDialog, onCancel, onBackdropClick, onKeydown } = useDialog(
  () => confirming.value,
  () => {
    if (!props.busy) confirming.value = false;
  },
);
function edit() {
  confirming.value = false;
  emit('edit');
}
</script>

<template>
  <section v-if="issues.length" class="run-skill-conflict" aria-label="技能冲突">
    <div role="alert">
      <strong>技能状态与原运行不一致</strong>
      <p v-for="(issue, index) in issues" :key="index">{{ skillIssueText(issue) }}</p>
    </div>
    <button v-if="run" type="button" :disabled="busy" @click="confirming = true">
      <Pencil :size="16" aria-hidden="true" />{{ active ? '取消运行并编辑' : '编辑原请求' }}
    </button>
    <dialog
      :ref="setDialog"
      class="run-edit-dialog"
      aria-label="确认编辑原请求"
      @cancel="onCancel"
      @click="onBackdropClick"
      @keydown="onKeydown"
    >
      <h3>编辑原请求</h3>
      <p v-if="active">原运行将先取消。已完成的工具操作不会撤销。</p>
      <p v-else>已完成的工具操作不会撤销。</p>
      <p v-if="completed.length">已完成：{{ completed.join('、') }}</p>
      <p>原输入和参数将载入草稿。再次发送会创建新运行，工具需要重新审批。</p>
      <p>当前草稿将替换为原请求。</p>
      <div>
        <button type="button" :disabled="busy" @click="confirming = false">返回</button
        ><button type="button" :disabled="busy" @click="edit">
          {{ active ? '确认取消并编辑' : '确认编辑' }}
        </button>
      </div>
    </dialog>
  </section>
</template>

<style scoped>
.run-skill-conflict {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  border-left: 3px solid #b45309;
  padding: 8px 12px;
  margin-bottom: 10px;
}
.run-skill-conflict > div {
  flex: 1 1 220px;
  min-width: 0;
  overflow-wrap: anywhere;
}
.run-skill-conflict p {
  margin: 4px 0;
  font-size: 13px;
}
.run-skill-conflict button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  white-space: normal;
}
.run-edit-dialog {
  width: min(440px, calc(100vw - 32px));
  max-height: calc(100dvh - 32px);
  box-sizing: border-box;
  overflow: auto;
  padding: 20px;
  border: 1px solid #d4d4d4;
  border-radius: 8px;
  background: white;
  color: #262626;
}
.run-edit-dialog::backdrop {
  background: #0006;
}
.run-edit-dialog h3 {
  margin: 0 0 12px;
  font-size: 18px;
}
.run-edit-dialog p {
  margin: 10px 0;
  line-height: 1.6;
  overflow-wrap: anywhere;
}
.run-edit-dialog > div {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}
</style>
