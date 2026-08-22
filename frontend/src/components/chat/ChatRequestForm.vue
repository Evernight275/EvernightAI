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
  text,
  canSubmit,
  providerDisabled,
  modelDisabled,
  submitLabel,
  submit,
} = useChatRequestForm(props, emit)
</script>

<template>
  <section>
    <h2>发送消息</h2>
    <form @submit.prevent="submit">
      <p>
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
      </p>

      <p>
        <label>
          Model ID
          <input
            v-model="modelId"
            :disabled="modelDisabled"
            autocomplete="off"
          />
        </label>
      </p>

      <p>
        <label>
          Message
          <textarea v-model="text" :disabled="busy"></textarea>
        </label>
      </p>

      <button type="submit" :disabled="!canSubmit">
        {{ submitLabel }}
      </button>
    </form>
  </section>
</template>
