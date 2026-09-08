<script setup lang="ts">
import WorkspaceView from '../workspace/WorkspaceView.vue'
import { useDialog } from '../common/dialog'
const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()
const { setDialog, onCancel, onBackdropClick, onKeydown } = useDialog(() => props.open, () => emit('close'))
</script>

<template>
  <dialog :ref="setDialog" class="settings-dialog" aria-label="设置"
    @cancel="onCancel" @click="onBackdropClick" @keydown="onKeydown">
    <WorkspaceView v-if="open" embedded @close="emit('close')" />
  </dialog>
</template>
