<script setup lang="ts">
import { onMounted } from 'vue';
import { KeyRound } from '@lucide/vue';
import { useAccountSettings } from './accountSettings';

const account = useAccountSettings({ redirect: (target) => window.location.assign(target) });

onMounted(account.load);
</script>

<template>
  <section class="settings-card settings-auth">
    <header class="settings-card-header">
      <span class="settings-card-icon" aria-hidden="true"><KeyRound :size="18" /></span>
      <div>
        <h2>账号</h2>
        <p>控制面板使用账号密码登录。</p>
      </div>
    </header>
    <p v-if="account.error.value" class="settings-feedback" role="alert">
      {{ account.error.value }}
    </p>
    <div v-if="account.identity.value" class="settings-help">
      <template v-if="account.identity.value.principal">
        <p>当前身份：{{ account.identity.value.principal.principal_id }}</p>
        <p>角色：{{ account.identity.value.principal.roles.join('、') || '未分配' }}</p>
        <p style="overflow-wrap: anywhere">
          权限：{{ account.identity.value.principal.permissions.join('、') || '未分配' }}
        </p>
      </template>
      <p v-else>当前服务未启用认证，无需登录。</p>
    </div>
    <div v-if="account.identity.value?.principal || account.error.value" class="settings-actions">
      <button
        v-if="account.identity.value?.principal"
        type="button"
        :disabled="account.busy.value"
        @click="account.signOut"
      >
        退出登录
      </button>
      <a v-else href="./login.html">前往登录</a>
    </div>
  </section>
</template>
