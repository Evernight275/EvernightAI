<script setup lang="ts">
import LoginForm from './components/auth/LoginForm.vue';

const heroImage =
  'https://act-upload.mihoyo.com/sr-wiki/2025/03/14/279865110/7b277871b64b02ef0fe74bf40bf64351_283784981328251574.png';
</script>

<template>
  <div class="login-layout">
    <div class="login-hero" aria-hidden="true">
      <img :src="heroImage" alt="" decoding="async" referrerpolicy="no-referrer" />
    </div>
    <main class="login-panel">
      <LoginForm />
    </main>
  </div>
</template>
