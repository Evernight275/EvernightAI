<script setup lang="ts">
import { ImagePlus, PanelLeftClose, Settings, SquarePen, X } from '@lucide/vue';
import { useSidebarDialog } from '../chat/chatLayout';

const props = defineProps<{ open: boolean; collapsed?: boolean }>();
const emit = defineEmits<{ close: []; collapse: []; settings: [] }>();
const { setDialog, onCancel, onBackdropClick, onKeydown } = useSidebarDialog(props, () =>
  emit('close'),
);
</script>

<template>
  <dialog
    :ref="setDialog"
    class="chat-sidebar-dialog"
    aria-label="页面导航"
    @cancel="onCancel"
    @click="onBackdropClick"
    @keydown="onKeydown"
  >
    <aside class="chat-sidebar">
      <header class="chat-sidebar-header">
        <button
          class="icon-button chat-navigation-close"
          type="button"
          aria-label="关闭页面导航"
          title="关闭页面导航"
          @click="$emit('close')"
        >
          <X :size="18" aria-hidden="true" />
        </button>
        <h1 class="chat-sidebar-brand">
          <span>EvernightAI</span>
        </h1>
        <button
          class="icon-button chat-sidebar-collapse"
          type="button"
          aria-label="收起侧栏"
          title="收起侧栏"
          @click="$emit('collapse')"
        >
          <PanelLeftClose :size="19" aria-hidden="true" />
        </button>
        <a class="chat-sidebar-new" href="/chat.html"
          ><SquarePen :size="18" aria-hidden="true" />会话</a
        >
        <a class="chat-sidebar-new" href="/images.html" aria-current="page"
          ><ImagePlus :size="18" aria-hidden="true" />图像生成</a
        >
      </header>
      <div></div>
      <footer class="chat-sidebar-settings">
        <button
          class="chat-sidebar-account"
          type="button"
          aria-label="设置"
          aria-haspopup="dialog"
          @click="$emit('settings')"
        >
          <span class="chat-sidebar-account-copy"
            ><strong>EvernightAI</strong><small>本地工作区</small></span
          >
          <Settings :size="17" aria-hidden="true" />
        </button>
      </footer>
    </aside>
  </dialog>
</template>
