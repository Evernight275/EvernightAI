<script setup lang="ts">
import { Eye, EyeOff, KeyRound } from '@lucide/vue'
import { useApiKeySettings } from './apiKeySettings'

const settings = useApiKeySettings()
</script>

<template>
  <section class="settings-card settings-auth">
    <header class="settings-card-header">
      <span class="settings-card-icon" aria-hidden="true"><KeyRound :size="18" /></span>
      <div>
        <h2>认证</h2>
        <p>为当前浏览器保存访问 EvernightAI 服务的凭证。</p>
      </div>
    </header>
    <form @submit.prevent="settings.save">
      <fieldset :disabled="settings.busy.value" class="settings-auth-fields">
      <label class="settings-field-label" for="credential-kind">凭证类型</label>
      <select id="credential-kind" v-model="settings.kind.value">
        <option value="api-key">API Key</option>
        <option value="bearer">Bearer Token</option>
      </select>
      <label class="settings-field-label" for="api-key">{{ settings.kind.value === 'bearer' ? 'Bearer Token' : 'API Key' }}</label>
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
        <button class="button-primary" type="submit" :disabled="!settings.apiKey.value.trim()">{{ settings.busy.value ? '验证中…' : '验证并保存' }}</button>
        <button type="button" @click="settings.refreshIdentity">查看当前身份</button>
        <button type="button" :disabled="!settings.canClear.value" @click="settings.clear">退出</button>
      </div>
      </fieldset>
      <p v-if="settings.error.value" class="settings-feedback" role="alert">{{ settings.error.value }}</p>
      <p v-if="settings.feedback.value" class="settings-feedback" role="status">{{ settings.feedback.value }}</p>
      <div v-if="settings.identity.value" class="settings-help">
        <template v-if="settings.identity.value.principal">
          <p>当前身份：{{ settings.identity.value.principal.principal_id }}</p>
          <p>角色：{{ settings.identity.value.principal.roles.join('、') || '未分配' }}</p>
          <p style="overflow-wrap: anywhere">权限：{{ settings.identity.value.principal.permissions.join('、') || '未分配' }}</p>
        </template>
        <p v-else>当前服务未启用认证。</p>
      </div>
    </form>
  </section>
</template>
