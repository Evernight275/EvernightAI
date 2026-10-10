import { computed, ref } from 'vue';
import {
  createApiKey,
  listApiKeys,
  revokeApiKey,
  type ApiKeyInfo,
  type IssuedApiKey,
} from '../../api/auth';
import { ApiError } from '../../api/client';

/** `login-required`: the browser holds no login session. `unavailable`: no password login. */
export type ApiKeyAccess = 'loading' | 'ready' | 'login-required' | 'unavailable';
export type ApiKeyStatus = 'active' | 'expired';

export function apiKeyStatus(key: ApiKeyInfo, now: Date = new Date()): ApiKeyStatus {
  if (key.expires_at && new Date(key.expires_at).getTime() <= now.getTime()) return 'expired';
  return 'active';
}

export function useApiKeyManager() {
  const access = ref<ApiKeyAccess>('loading');
  const keys = ref<ApiKeyInfo[]>([]);
  const name = ref('');
  const expiresAt = ref('');
  const issued = ref<IssuedApiKey | null>(null);
  const pendingRevoke = ref<ApiKeyInfo | null>(null);
  const busy = ref(false);
  const error = ref<string | null>(null);
  const canCreate = computed(() => !busy.value && name.value.trim() !== '');

  async function perform(action: () => Promise<void>): Promise<void> {
    if (busy.value) return;
    busy.value = true;
    error.value = null;
    try {
      await action();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        access.value = 'login-required';
        issued.value = null;
        pendingRevoke.value = null;
      } else {
        error.value = cause instanceof Error ? cause.message : '操作失败';
      }
    } finally {
      busy.value = false;
    }
  }

  async function refresh(): Promise<void> {
    // The service keeps revoked keys in its listing; a revoked key is simply gone here.
    keys.value = (await listApiKeys()).filter((key) => !key.revoked_at);
    access.value = 'ready';
  }

  function load(): Promise<void> {
    return perform(async () => {
      try {
        await refresh();
      } catch (cause) {
        if (!(cause instanceof ApiError) || cause.status !== 404) throw cause;
        access.value = 'unavailable';
      }
    });
  }

  function create(): Promise<void> {
    if (!canCreate.value) return Promise.resolve();
    return perform(async () => {
      // The field holds local wall time; the service requires a timezone.
      const expiry = expiresAt.value ? new Date(expiresAt.value) : null;
      if (expiry && Number.isNaN(expiry.getTime())) throw new Error('过期时间无效');
      issued.value = await createApiKey(name.value.trim(), expiry ? expiry.toISOString() : null);
      name.value = '';
      expiresAt.value = '';
      await refresh();
    });
  }

  function revoke(): Promise<void> {
    const key = pendingRevoke.value;
    if (!key) return Promise.resolve();
    return perform(async () => {
      await revokeApiKey(key.key_id);
      pendingRevoke.value = null;
      if (issued.value?.key.key_id === key.key_id) issued.value = null;
      await refresh();
    });
  }

  function dismissIssued(): void {
    issued.value = null;
  }

  return {
    access,
    keys,
    name,
    expiresAt,
    issued,
    pendingRevoke,
    busy,
    error,
    canCreate,
    load,
    create,
    revoke,
    dismissIssued,
  };
}
