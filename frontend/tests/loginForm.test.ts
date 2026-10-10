import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getAuthOptions, getIdentity, login } from '../src/api/auth';
vi.mock('../src/api/auth', () => ({
  getAuthOptions: vi.fn(),
  getIdentity: vi.fn(),
  login: vi.fn(),
}));
import { ApiError } from '../src/api/client';
import { loginRedirectTarget, useLoginForm } from '../src/components/auth/loginForm';

const principal = {
  principal_id: 'admin',
  principal_type: 'user',
  roles: [],
  permissions: ['*'],
};

function apiError(status: number, message = 'failed'): ApiError {
  return new ApiError(message, {
    status,
    path: '/auth/login',
    requestId: null,
    errorType: null,
    detail: null,
  });
}

describe('login form controller', () => {
  beforeEach(() => {
    vi.mocked(getAuthOptions)
      .mockReset()
      .mockResolvedValue({ authentication_enabled: true, login_enabled: true });
    vi.mocked(getIdentity).mockReset().mockRejectedValue(apiError(401));
    vi.mocked(login).mockReset().mockResolvedValue({
      access_token: 'session-token',
      token_type: 'bearer',
      expires_at: '2026-01-01T12:00:00Z',
      principal,
    });
    vi.stubGlobal('localStorage', new MemoryStorage());
    vi.stubGlobal('window', { dispatchEvent: vi.fn() });
  });

  it('shows the form when the browser has no valid credential', async () => {
    const redirect = vi.fn();
    const form = useLoginForm({ redirect });

    await form.start();

    expect(form.checking.value).toBe(false);
    expect(form.loginAvailable.value).toBe(true);
    expect(form.error.value).toBeNull();
    expect(redirect).not.toHaveBeenCalled();
  });

  it('skips the form when this browser is already signed in', async () => {
    vi.mocked(getIdentity).mockResolvedValue({ authentication_enabled: true, principal });
    const redirect = vi.fn();

    await useLoginForm({ redirect, search: '?redirect=/index.html' }).start();

    expect(redirect).toHaveBeenCalledWith('/index.html');
  });

  it('skips the form without asking for an identity when the service is open', async () => {
    vi.mocked(getAuthOptions).mockResolvedValue({
      authentication_enabled: false,
      login_enabled: false,
    });
    const redirect = vi.fn();

    await useLoginForm({ redirect }).start();

    expect(redirect).toHaveBeenCalledWith('./chat.html');
    expect(getIdentity).not.toHaveBeenCalled();
  });

  it('replaces the form with a notice when password login is not configured', async () => {
    vi.mocked(getAuthOptions).mockResolvedValue({
      authentication_enabled: true,
      login_enabled: false,
    });
    const redirect = vi.fn();
    const form = useLoginForm({ redirect });

    await form.start();

    expect(form.checking.value).toBe(false);
    expect(form.loginAvailable.value).toBe(false);
    expect(form.error.value).toBeNull();
    expect(redirect).not.toHaveBeenCalled();
  });

  it('reports an unreachable service but still offers the form', async () => {
    for (const fail of [
      () => vi.mocked(getAuthOptions).mockRejectedValue(new TypeError('Failed to fetch')),
      () => vi.mocked(getIdentity).mockRejectedValue(apiError(503)),
    ]) {
      fail();
      const form = useLoginForm({ redirect: vi.fn() });

      await form.start();

      expect(form.checking.value).toBe(false);
      expect(form.loginAvailable.value).toBe(true);
      expect(form.error.value).toBe('无法连接服务，请确认服务已启动后重试。');
    }
  });

  it('stores the session token and redirects after a successful login', async () => {
    localStorage.setItem('evernight.apiKey', 'old-key');
    const redirect = vi.fn();
    const form = useLoginForm({ redirect });
    form.username.value = '  admin ';
    form.password.value = ' spaced secret ';

    await form.submit();

    expect(login).toHaveBeenCalledWith('admin', ' spaced secret ');
    expect(localStorage.getItem('evernight.accessToken')).toBe('session-token');
    expect(localStorage.getItem('evernight.apiKey')).toBeNull();
    expect(form.password.value).toBe('');
    expect(redirect).toHaveBeenCalledWith('./chat.html');
  });

  it('keeps the user on the form with a clear message when login is rejected', async () => {
    const redirect = vi.fn();
    const form = useLoginForm({ redirect });
    form.username.value = 'admin';
    form.password.value = 'wrong';

    vi.mocked(login).mockRejectedValue(apiError(401, 'Invalid username or password'));
    await form.submit();
    expect(form.error.value).toBe('用户名或密码不正确。');

    vi.mocked(login).mockRejectedValue(apiError(404));
    await form.submit();
    expect(form.error.value).toBe('服务未启用密码登录，请在 config.toml 中配置用户。');

    vi.mocked(login).mockRejectedValue(new TypeError('Failed to fetch'));
    await form.submit();
    expect(form.error.value).toBe('无法连接服务，请稍后重试。');

    expect(localStorage.getItem('evernight.accessToken')).toBeNull();
    expect(form.password.value).toBe('wrong');
    expect(form.busy.value).toBe(false);
    expect(redirect).not.toHaveBeenCalled();
  });

  it('does not submit until both fields are filled', async () => {
    const form = useLoginForm({ redirect: vi.fn() });

    form.username.value = '   ';
    form.password.value = 'secret';
    await form.submit();
    form.username.value = 'admin';
    form.password.value = '';
    await form.submit();

    expect(form.canSubmit.value).toBe(false);
    expect(login).not.toHaveBeenCalled();
  });

  it('toggles password visibility', () => {
    const form = useLoginForm({ redirect: vi.fn() });

    expect(form.inputType.value).toBe('password');
    form.toggleReveal();
    expect(form.inputType.value).toBe('text');
    expect(form.revealLabel.value).toBe('隐藏');
  });
});

describe('login redirect target', () => {
  it('follows same-origin paths and keeps their query', () => {
    expect(loginRedirectTarget('?redirect=/index.html')).toBe('/index.html');
    expect(loginRedirectTarget('?redirect=%2Fchat.html%3Fsession%3D1')).toBe(
      '/chat.html?session=1',
    );
  });

  it('falls back to chat for missing or off-site targets', () => {
    for (const search of [
      '',
      '?redirect=',
      '?redirect=https://evil.example',
      '?redirect=//evil.example',
      '?redirect=/%5Cevil.example',
      '?redirect=/%0A/evil.example',
      '?redirect=/%09/evil.example',
      '?redirect=/%0D%5Cevil.example',
      '?redirect=javascript:alert(1)',
      '?redirect=chat.html',
    ]) {
      expect(loginRedirectTarget(search)).toBe('./chat.html');
    }
  });
});

class MemoryStorage implements Storage {
  private readonly values = new Map<string, string>();

  get length(): number {
    return this.values.size;
  }

  clear(): void {
    this.values.clear();
  }

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  key(index: number): string | null {
    return [...this.values.keys()][index] ?? null;
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}
