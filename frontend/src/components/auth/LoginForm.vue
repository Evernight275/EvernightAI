<script setup lang="ts">
import { onMounted } from 'vue';
import { useLoginForm } from './loginForm';

const {
  username,
  password,
  inputType,
  revealed,
  revealLabel,
  checking,
  loginAvailable,
  busy,
  error,
  canSubmit,
  toggleReveal,
  start,
  submit,
} = useLoginForm({
  redirect: (target) => window.location.assign(target),
  search: window.location.search,
});

onMounted(start);
</script>

<template>
  <section class="login-card" aria-labelledby="login-title">
    <header class="login-card__header">
      <p class="login-card__brand">EvernightAI</p>
      <h1 id="login-title">登录</h1>
      <p class="login-card__lead">使用管理员账号进入控制面板。</p>
    </header>

    <p v-if="checking" class="login-card__status" role="status">正在检查登录状态…</p>

    <div v-else-if="!loginAvailable" class="login-card__notice">
      <p>此服务未启用密码登录。</p>
      <p>请在设置中填写 API Key 或访问令牌。</p>
      <a class="login-card__link" href="./chat.html">前往控制面板</a>
    </div>

    <form v-else class="login-form" novalidate @submit.prevent="submit">
      <label class="login-field" for="login-username">
        <span>用户名</span>
        <input
          id="login-username"
          v-model="username"
          name="username"
          type="text"
          autocomplete="username"
          autocapitalize="none"
          spellcheck="false"
          autofocus
          :disabled="busy"
        />
      </label>

      <label class="login-field" for="login-password">
        <span>密码</span>
        <span class="login-field__control">
          <input
            id="login-password"
            v-model="password"
            name="password"
            :type="inputType"
            autocomplete="current-password"
            :disabled="busy"
          />
          <button
            type="button"
            class="login-field__reveal"
            :aria-pressed="revealed"
            @click="toggleReveal"
          >
            {{ revealLabel }}
          </button>
        </span>
      </label>

      <p v-if="error" class="login-form__error" role="alert">{{ error }}</p>

      <button type="submit" class="button-primary login-form__submit" :disabled="!canSubmit">
        {{ busy ? '正在登录…' : '登录' }}
      </button>
    </form>
  </section>
</template>
