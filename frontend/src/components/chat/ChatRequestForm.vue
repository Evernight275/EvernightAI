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
