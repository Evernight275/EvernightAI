<script setup lang="ts">
import { onMounted, ref } from 'vue';
import type { ApiKeyInfo } from '../../api/auth';
import { apiKeyStatus, useApiKeyManager } from './apiKeyManager';

const manager = useApiKeyManager();
const copied = ref(false);
const statusLabels = { active: '有效', expired: '已过期' };
const loginHref = `./login.html?redirect=${encodeURIComponent(
  window.location.pathname + window.location.search + window.location.hash,
)}`;

function time(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false });
}
function describe(key: ApiKeyInfo): string {
  const expiry = key.expires_at ? `${time(key.expires_at)} 过期` : '永不过期';
  return `${key.prefix}… · 创建于 ${time(key.created_at)} · ${expiry}`;
}
async function copy(): Promise<void> {
  if (!manager.issued.value) return;
  await navigator.clipboard.writeText(manager.issued.value.api_key);
  copied.value = true;
}
function dismiss(): void {
  copied.value = false;
  manager.dismissIssued();
}

onMounted(manager.load);
</script>

<template>
  <section
    v-if="manager.access.value !== 'unavailable'"
    class="settings-card settings-manager"
    aria-label="生成的 API Key"
  >
    <header class="settings-card-header">
      <div>
        <h2>生成的 API Key</h2>
        <p>
          供 curl、Python 等脚本和集成调用接口使用，继承当前账号的身份与权限。此页面不使用它登录。
        </p>
      </div>
    </header>
    <p v-if="manager.error.value" class="settings-feedback" role="alert">
      {{ manager.error.value }}
    </p>
    <p v-if="manager.access.value === 'loading'" class="settings-help" role="status">正在加载…</p>
    <p v-else-if="manager.access.value === 'login-required'" class="settings-help">
      生成、查看和吊销 API Key 需要先用账号密码登录。
      <a :href="loginHref">前往登录</a>
    </p>
    <template v-else>
      <div
        v-if="manager.issued.value"
        class="settings-confirm"
        role="group"
        aria-label="新生成的密钥"
      >
        <p>「{{ manager.issued.value.key.name }}」已生成。完整密钥只显示这一次，请立即保存：</p>
        <p>
          <code>{{ manager.issued.value.api_key }}</code>
        </p>
        <button type="button" @click="copy">{{ copied ? '已复制' : '复制密钥' }}</button
        ><button type="button" @click="dismiss">我已保存</button>
      </div>
      <p v-if="!manager.keys.value.length" class="settings-help">还没有生成过密钥。</p>
      <div v-for="key in manager.keys.value" :key="key.key_id" class="settings-row">
        <div>
          <h3>{{ key.name }} · {{ statusLabels[apiKeyStatus(key)] }}</h3>
          <p>{{ describe(key) }}</p>
        </div>
        <button
          type="button"
          :disabled="manager.busy.value"
          :aria-label="`吊销密钥 ${key.name}`"
          @click="manager.pendingRevoke.value = key"
        >
          吊销
        </button>
      </div>
      <div
        v-if="manager.pendingRevoke.value"
        class="settings-confirm"
        role="group"
        aria-label="吊销密钥确认"
      >
        <p>
          吊销「{{
            manager.pendingRevoke.value.name
          }}」？使用它的脚本会立即失去访问权限，且无法恢复。
        </p>
        <button
          type="button"
          :disabled="manager.busy.value"
          @click="manager.pendingRevoke.value = null"
        >
          取消</button
        ><button type="button" :disabled="manager.busy.value" @click="manager.revoke">
          确认吊销密钥
        </button>
      </div>
      <form class="settings-form" @submit.prevent="manager.create">
        <h3>生成新密钥</h3>
        <fieldset :disabled="manager.busy.value">
          <label
            >密钥名称<input
              v-model="manager.name.value"
              required
              maxlength="120"
              placeholder="例如：automation"
          /></label>
          <label
            >过期时间（可选）<input v-model="manager.expiresAt.value" type="datetime-local"
          /></label>
          <div class="settings-inline-actions">
            <button class="button-primary" :disabled="!manager.canCreate.value">生成密钥</button>
          </div>
        </fieldset>
      </form>
    </template>
  </section>
</template>
