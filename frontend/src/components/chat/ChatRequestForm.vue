<script setup lang="ts">
import ChatModelPicker from './ChatModelPicker.vue';
import { ArrowUp, Square } from '@lucide/vue';
import {
  useChatRequestForm,
  type ChatRequestFormEmits,
  type ChatRequestFormProps,
} from './chatRequestForm';

const props = defineProps<ChatRequestFormProps>();
const emit = defineEmits<ChatRequestFormEmits>();
const {
  inputJson,
  draftNotice,
  optionsError,
  providerId,
  modelId,
  text,
  setTextarea,
  canSubmit,
  selectedProviderDisabled,
  providerDisabled,
  messageDisabled,
  submitLabel,
  handleMessageKeydown,
  submit,
} = useChatRequestForm(props, emit);
</script>

<template>
  <section class="chat-composer">
    <p v-if="optionsError" role="alert">{{ optionsError }}</p>
    <p v-if="draftNotice" role="status">{{ draftNotice }}</p>
    <p v-if="selectedProviderDisabled" role="status">
      当前模型服务已停用，请启用该服务或选择其他模型。
    </p>
    <h2 class="sr-only">发送消息</h2>
    <form @submit.prevent="submit">
      <div class="chat-composer-message">
        <label class="sr-only" for="chat-message">{{
          inputJson ? '输入消息（JSON）' : '消息'
        }}</label>
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
          <ChatModelPicker
            :catalog="catalog"
            :provider-id="providerId"
            :model-id="modelId"
            :disabled="providerDisabled"
            @select="
              (provider, model) => {
                providerId = provider;
                modelId = model;
              }
            "
          />
        </div>

        <button
          v-if="canStop"
          class="chat-composer-submit"
          type="button"
          aria-label="停止当前运行"
          title="停止当前运行"
          @click="emit('cancel')"
        >
          <Square :size="16" aria-hidden="true" />
        </button>
        <button
          v-else
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
