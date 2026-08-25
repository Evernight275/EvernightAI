<script setup lang="ts">
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
  submit,
} = useChatRequestForm(props, emit)
</script>

<template>
  <section class="chat-composer">
    <h2>发送消息</h2>
    <form @submit.prevent="submit">
      <div class="chat-composer-message">
        <label for="chat-message">
          Message
        </label>
        <textarea
          id="chat-message"
          v-model="text"
          :disabled="messageDisabled"
        ></textarea>
      </div>

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
          Model ID
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

      <button type="submit" :disabled="!canSubmit">
        {{ submitLabel }}
      </button>
    </form>
  </section>
</template>
