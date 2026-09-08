<script setup lang="ts">
import { Eye, EyeOff, KeyRound } from '@lucide/vue'
import { useApiKeySettings } from './apiKeySettings'

const settings = useApiKeySettings()
</script>

<template>
  <section class="settings-card">
    <header class="settings-card-header">
      <span class="settings-card-icon" aria-hidden="true"><KeyRound :size="18" /></span>
      <div>
        <h2>认证</h2>
        <p>为当前浏览器保存访问 EvernightAI 服务的凭证。</p>
      </div>
    </header>
    <form @submit.prevent="settings.save">
      <label class="settings-field-label" for="api-key">API Key</label>
      <div class="settings-secret-field">
        <input id="api-key" :type="settings.inputType.value" :value="settings.apiKey.value"
          autocomplete="off" spellcheck="false" placeholder="输入 API Key" @input="settings.handleInput" />
        <button class="settings-reveal" type="button" :aria-label="settings.revealLabel.value + ' API Key'"
          :title="settings.revealLabel.value + ' API Key'" @click="settings.toggleReveal">
          <EyeOff v-if="settings.revealed.value" :size="17" aria-hidden="true" />
          <Eye v-else :size="17" aria-hidden="true" />
        </button>
      </div>
      <p class="settings-help">凭证仅保存在本地浏览器存储中，请勿在共享设备上保存。</p>
      <div class="settings-actions">
        <button class="button-primary" type="submit" :disabled="!settings.changed.value">保存</button>
        <button type="button" :disabled="!settings.canClear.value" @click="settings.clear">清除</button>
      </div>
      <p v-if="settings.feedback.value" class="settings-feedback" role="status">{{ settings.feedback.value }}</p>
    </form>
  </section>
</template>
