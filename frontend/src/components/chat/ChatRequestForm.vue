<script setup lang="ts">
import ChatModelPicker from './ChatModelPicker.vue';
import { ArrowUp, ImagePlus, Square, X } from '@lucide/vue';
import { ref, watch } from 'vue';
import { useDialog } from '../common/dialog';
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
  attachmentError,
  attachments,
  uploading,
  addFiles,
  remove,
  retry,
  handleFileChange,
  imageCapabilityUnsupported,
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
const previewSource = ref('');
const previewName = ref('');
const previewDialog = useDialog(
  () => !!previewSource.value,
  () => (previewSource.value = ''),
);
watch(
  () => attachments.value.some((item) => item.previewUrl === previewSource.value),
  (available) => {
    if (!available) previewSource.value = '';
  },
);
</script>

<template>
  <section class="chat-composer">
    <p v-if="optionsError" role="alert">{{ optionsError }}</p>
    <p v-if="attachmentError" role="alert">{{ attachmentError }}</p>
    <span v-if="uploading" class="sr-only" role="status">正在上传图片</span>
    <p v-if="imageCapabilityUnsupported" role="status">
      所选模型已声明不支持图像识别，请选择支持图片的模型。
    </p>
    <p v-if="draftNotice" role="status">{{ draftNotice }}</p>
    <p v-if="selectedProviderDisabled" role="status">
      当前模型服务已停用，请启用该服务或选择其他模型。
    </p>
    <h2 class="sr-only">发送消息</h2>
    <form
      @submit.prevent="submit"
      @dragover.prevent
      @drop.prevent="addFiles(($event as DragEvent).dataTransfer?.files || [])"
    >
      <div v-if="attachments.length" class="chat-attachments" aria-label="图片附件">
        <div
          v-for="(attachment, index) in attachments"
          :key="attachment.artifact.artifact_id"
          class="chat-attachment"
        >
          <button
            v-if="attachment.previewUrl"
            type="button"
            class="chat-attachment-preview"
            :aria-label="`预览 ${attachment.artifact.name}`"
            @click="
              previewSource = attachment.previewUrl;
              previewName = attachment.artifact.name;
            "
          >
            <img :src="attachment.previewUrl" :alt="attachment.artifact.name" />
          </button>
          <div v-else class="chat-attachment-placeholder" aria-hidden="true">图片</div>
          <span class="chat-attachment-name">{{ attachment.artifact.name }}</span>
          <span v-if="attachment.status === 'loading'" role="status">{{
            uploading ? '正在上传…' : '正在载入…'
          }}</span>
          <span v-if="attachment.status === 'error'" class="chat-attachment-error" role="alert">{{
            attachment.error
          }}</span>
          <button v-if="attachment.status === 'error'" type="button" @click="retry(index)">
            重试
          </button>
          <button
            type="button"
            class="chat-attachment-remove"
            :aria-label="`移除 ${attachment.artifact.name}`"
            @click="remove(index)"
          >
            <X :size="14" aria-hidden="true" />
          </button>
        </div>
      </div>
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
          @paste="
            addFiles(
              Array.from(($event as ClipboardEvent).clipboardData?.files || []).filter((file) =>
                file.type.startsWith('image/'),
              ) as File[],
            )
          "
        ></textarea>
      </div>

      <div class="chat-composer-actions">
        <div class="chat-composer-options">
          <label class="chat-attachment-button" title="添加图片">
            <ImagePlus :size="18" aria-hidden="true" />
            <span class="sr-only">添加图片</span>
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              multiple
              :disabled="busy || !sessionReady"
              @change="handleFileChange"
            />
          </label>
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
    <dialog
      :ref="previewDialog.setDialog"
      class="chat-image-preview-dialog"
      :aria-label="`图片预览：${previewName}`"
      @cancel="previewDialog.onCancel"
      @click="previewDialog.onBackdropClick"
      @keydown="previewDialog.onKeydown"
    >
      <button type="button" aria-label="关闭图片预览" @click="previewSource = ''">关闭</button>
      <img v-if="previewSource" :src="previewSource" :alt="previewName" />
    </dialog>
  </section>
</template>
