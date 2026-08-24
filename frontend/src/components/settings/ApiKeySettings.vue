<script setup lang="ts">
import { useApiKeySettings } from './apiKeySettings'

const settings = useApiKeySettings()
</script>

<template>
  <section>
    <h2>认证</h2>
    <form @submit.prevent="settings.save">
      <p>
        <label for="api-key">API Key</label><br />
        <input
          id="api-key"
          :type="settings.inputType.value"
          :value="settings.apiKey.value"
          autocomplete="off"
          spellcheck="false"
          @input="settings.handleInput"
        />
        <button type="button" @click="settings.toggleReveal">
          {{ settings.revealLabel.value }}
        </button>
      </p>
      <p>
        <button type="submit" :disabled="!settings.changed.value">保存</button>
        <button type="button" :disabled="!settings.canClear.value" @click="settings.clear">
          清除
        </button>
      </p>
      <p v-if="settings.feedback.value" role="status">{{ settings.feedback.value }}</p>
    </form>
  </section>
</template>
