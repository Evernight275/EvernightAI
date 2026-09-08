<script setup lang="ts">
import { Send, Square } from '@lucide/vue'
import {
  useChatRequestForm,
  type ChatRequestFormEmits,
  type ChatRequestFormProps,
} from './chatRequestForm'

const props = defineProps<ChatRequestFormProps>()
const emit = defineEmits<ChatRequestFormEmits>()
const {
  providerId,
  modelId,
  models,
  text,
  canSubmit,
  providerDisabled,
  modelDisabled,
  messageDisabled,
  submitLabel,
  handleMessageKeydown,
  submit,
} = useChatRequestForm(props, emit)
</script>

<template>
  <section class="chat-composer">
    <h2 class="sr-only">发送消息</h2>
    <form @submit.prevent="submit">
      <div class="chat-composer-message">
        <label class="sr-only" for="chat-message">消息</label>
        <textarea
          id="chat-message"
          v-model="text"
          :disabled="messageDisabled"
          placeholder="输入消息"
          @keydown="handleMessageKeydown"
        ></textarea>
      </div>

      <div class="chat-composer-actions">
        <div class="chat-composer-options">
          <label>
            Provider
            <select v-model="providerId" :disabled="providerDisabled">
              <option value="">请选择</option>
              <option
                v-for="provider in catalog.providers"
                :key="provider.provider_id"
                :value="provider.provider_id"
              >
                {{ provider.name }}（{{ provider.provider_id }}）
              </option>
            </select>
          </label>

          <label>
            Model
            <select v-model="modelId" :disabled="modelDisabled">
              <option value="">请选择</option>
              <option
                v-for="model in models"
                :key="model.model_id"
                :value="model.model_id"
              >
                {{ model.model_id }}
              </option>
            </select>
          </label>
        </div>

        <button v-if="canStop" class="chat-composer-submit" type="button"
          aria-label="停止当前运行" title="停止当前运行" @click="emit('cancel')">
          <Square :size="16" aria-hidden="true" /> 停止
        </button>
        <button v-else
          class="button-primary chat-composer-submit"
          type="submit"
          :disabled="!canSubmit"
        >
          <Send :size="16" aria-hidden="true" />
          {{ submitLabel }}
        </button>
      </div>
    </form>
  </section>
</template>
