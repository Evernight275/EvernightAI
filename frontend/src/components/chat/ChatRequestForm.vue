<script setup lang="ts">
import ChatModelPicker from './ChatModelPicker.vue'
import { ArrowUp, Square } from '@lucide/vue'
import {
  useChatRequestForm,
  type ChatRequestFormEmits,
  type ChatRequestFormProps,
} from './chatRequestForm'

const props = defineProps<ChatRequestFormProps>()
const emit = defineEmits<ChatRequestFormEmits>()
const {
  selectedSkill, skillVariables, optionsError, preview, previewing, previewContext,
  providerId,
  modelId,
  text,
  setTextarea,
  canSubmit,
  providerDisabled,
  messageDisabled,
  submitLabel,
  handleMessageKeydown,
  submit,
} = useChatRequestForm(props, emit)
</script>

<template>
  <section class="chat-composer">
    <details class="chat-advanced">
      <summary>技能与上下文</summary>
      <div class="settings-form">
        <label>模型 ID<input v-model="modelId" :disabled="busy" placeholder="可直接输入服务支持的模型 ID" /></label>
        <label v-if="skills?.length">本轮技能<select v-model="selectedSkill" :disabled="busy"><option value="">不使用技能</option><option v-for="skill in skills" :key="skill.name" :value="skill.name">{{ skill.name }} — {{ skill.description }}</option></select></label>
        <label v-if="selectedSkill">技能参数（JSON）<textarea v-model="skillVariables" :disabled="busy" rows="3" /></label>
        <details v-if="selectedSkill"><summary>查看技能参数说明</summary><pre>{{ JSON.stringify(skills?.find(skill => skill.name === selectedSkill)?.input_schema, null, 2) }}</pre></details>
        <button v-if="contextId" type="button" :disabled="busy || previewing || !modelId" @click="previewContext">{{ previewing ? '正在预览…' : '预览上下文' }}</button>
        <p v-else class="settings-help">创建会话后可预览上下文。</p>
        <pre v-if="preview" aria-label="上下文预览">{{ preview }}</pre>
      </div>
    </details>
    <p v-if="optionsError" role="alert">{{ optionsError }}</p>
    <h2 class="sr-only">发送消息</h2>
    <form @submit.prevent="submit">
      <div class="chat-composer-message">
        <label class="sr-only" for="chat-message">消息</label>
        <textarea
          id="chat-message"
          :ref="setTextarea"
          rows="1"
          v-model="text"
          :disabled="messageDisabled"
          placeholder="发送消息给 EvernightAI"
          @keydown="handleMessageKeydown"
        ></textarea>
      </div>

      <div class="chat-composer-actions">
        <div class="chat-composer-options">
          <ChatModelPicker :catalog="catalog" :provider-id="providerId" :model-id="modelId"
            :disabled="providerDisabled" @select="(provider, model) => { providerId = provider; modelId = model }" />
        </div>

        <button v-if="canStop" class="chat-composer-submit" type="button"
          aria-label="停止当前运行" title="停止当前运行" @click="emit('cancel')">
          <Square :size="16" aria-hidden="true" />
        </button>
        <button v-else
          class="button-primary chat-composer-submit"
          type="submit"
          :disabled="!canSubmit"
          :aria-label="submitLabel"
          :title="submitLabel"
        >
          <ArrowUp :size="20" aria-hidden="true" />
        </button>
      </div>
    </form>
  </section>
</template>
