import { computed, ref } from 'vue';
import { getAuthOptions, getIdentity, login } from '../../api/auth';
import { ApiError, setAccessToken } from '../../api/client';

export const defaultLoginRedirect = './chat.html';

export type LoginFormOptions = {
  redirect: (target: string) => void;
  search?: string;
};

export function loginRedirectTarget(search: string): string {
  const target = new URLSearchParams(search).get('redirect');
  // Only same-origin paths: "//host" and "/\host" would leave the site.
  if (!target || !/^\/(?![/\\])/.test(target)) return defaultLoginRedirect;
  try {
    if (new URL(target, 'https://evernight.invalid').origin !== 'https://evernight.invalid') {
      return defaultLoginRedirect;
    }
  } catch {
    return defaultLoginRedirect;
  }
  return target;
}

export function useLoginForm(options: LoginFormOptions) {
  const username = ref('');
  const password = ref('');
  const revealed = ref(false);
  const checking = ref(true);
  const loginAvailable = ref(true);
  const busy = ref(false);
  const error = ref<string | null>(null);
  const target = loginRedirectTarget(options.search ?? '');
  const inputType = computed(() => (revealed.value ? 'text' : 'password'));
  const revealLabel = computed(() => (revealed.value ? '隐藏' : '显示'));
  const canSubmit = computed(
    () => !busy.value && username.value.trim() !== '' && password.value !== '',
  );

  function toggleReveal(): void {
    revealed.value = !revealed.value;
  }

  /** Skip the form when the service is open or this browser is already signed in. */
  async function start(): Promise<void> {
    try {
      const authOptions = await getAuthOptions();
      if (!authOptions.authentication_enabled || (await isSignedIn())) {
        options.redirect(target);
        return;
      }
      loginAvailable.value = authOptions.login_enabled;
    } catch {
      error.value = '无法连接服务，请确认服务已启动后重试。';
    }
    checking.value = false;
  }

  async function isSignedIn(): Promise<boolean> {
    try {
      return Boolean((await getIdentity()).principal);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) return false;
      throw cause;
    }
  }

  async function submit(): Promise<void> {
    if (!canSubmit.value) return;
    busy.value = true;
    error.value = null;
    try {
      const session = await login(username.value.trim(), password.value);
      setAccessToken(session.access_token);
      password.value = '';
      options.redirect(target);
    } catch (cause) {
      error.value = loginErrorMessage(cause);
    } finally {
      busy.value = false;
    }
  }

  return {
    username,
    password,
    revealed,
    inputType,
    revealLabel,
    checking,
    loginAvailable,
    busy,
    error,
    canSubmit,
    toggleReveal,
    start,
    submit,
  };
}

function loginErrorMessage(cause: unknown): string {
  if (cause instanceof ApiError) {
    if (cause.status === 401) return '用户名或密码不正确。';
    if (cause.status === 404) return '服务未启用密码登录，请在 config.toml 中配置用户。';
    return cause.message;
  }
  return '无法连接服务，请稍后重试。';
}
