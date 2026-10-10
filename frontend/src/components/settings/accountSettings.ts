import { ref } from 'vue';
import { getIdentity, logout, type AuthSession } from '../../api/auth';
import { signOut as clearSession } from '../../api/client';

export type AccountSettingsOptions = {
  redirect: (target: string) => void;
};

export function useAccountSettings(options: AccountSettingsOptions) {
  const identity = ref<AuthSession | null>(null);
  const error = ref<string | null>(null);
  const busy = ref(false);

  async function load(): Promise<void> {
    if (busy.value) return;
    busy.value = true;
    error.value = null;
    try {
      identity.value = await getIdentity();
    } catch (cause) {
      identity.value = null;
      error.value = cause instanceof Error ? cause.message : '无法读取身份。';
    } finally {
      busy.value = false;
    }
  }

  async function signOut(): Promise<void> {
    if (busy.value) return;
    busy.value = true;
    try {
      // The browser signs out even when the session is already gone or the service is down.
      await logout().catch(() => undefined);
    } finally {
      busy.value = false;
    }
    clearSession();
    options.redirect('./login.html');
  }

  return { identity, error, busy, load, signOut };
}
