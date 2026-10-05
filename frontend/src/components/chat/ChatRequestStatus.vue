<script setup lang="ts">
import { Play, RotateCcw } from '@lucide/vue';
import { ref, watch } from 'vue';
import {
  useChatRequestStatus,
  type ChatRequestStatusEmits,
  type ChatRequestStatusProps,
} from './chatRequestStatus';

const props = defineProps<ChatRequestStatusProps>();
const emit = defineEmits<ChatRequestStatusEmits>();
const { visible, errorMessage, canRetry, canResume } = useChatRequestStatus(props);
const confirming = ref(false);
watch([() => props.runId, () => props.state, () => props.error], () => {
  confirming.value = false;
});
function retry() {
  if (props.retryTools?.length) confirming.value = true;
  else emit('retry');
}
function confirmRetry() {
  confirming.value = false;
  emit('retry');
}
</script>

<template>
  <section v-if="visible" class="chat-request-status" aria-label="待处理事项">
    <div v-if="errorMessage || canRetry" class="chat-notice">
      <p class="chat-status-error" role="alert">{{ errorMessage || '运行失败' }}</p>
      <button v-if="canRetry && !confirming" type="button" @click="retry">
        <RotateCcw :size="16" aria-hidden="true" /> 重试
      </button>
      <button type="button" @click="$emit('details')">查看详情</button>
    </div>
    <div
      v-if="canRetry && confirming"
      class="chat-retry-confirmation"
      role="group"
      aria-label="确认重试"
    >
      <p>
        重试将重新执行原请求。以下工具已开始执行，可能已产生结果：{{
          retryTools?.join('、')
        }}。重新执行可能重复生图、写文件或运行命令，请先查看已有结果。
      </p>
      <button
        v-if="canReplyOnly"
        type="button"
        @click="
          confirming = false;
          $emit('replyOnly');
        "
      >
        仅重试回复
      </button>
      <button type="button" @click="confirmRetry">确认重新执行</button>
      <button type="button" @click="confirming = false">取消重试</button>
    </div>
    <div v-if="workspaceNotice" class="chat-notice">
      <p role="status">{{ workspaceNotice }}</p>
      <button type="button" @click="$emit('details')">查看详情</button>
    </div>
    <div v-if="canResume" class="chat-notice">
      <p role="status">运行已暂停</p>
      <button type="button" @click="$emit('resume')">
        <Play :size="16" aria-hidden="true" /> 继续运行
      </button>
    </div>
  </section>
</template>

<style scoped>
.chat-retry-confirmation {
  border: 1px solid var(--color-border);
  border-radius: 10px;
  padding: 12px;
  margin: 8px 0;
  font-size: 13px;
}
.chat-retry-confirmation p {
  margin: 0 0 10px;
  overflow-wrap: anywhere;
  line-height: 1.6;
}
.chat-retry-confirmation button {
  margin-right: 8px;
}
</style>
