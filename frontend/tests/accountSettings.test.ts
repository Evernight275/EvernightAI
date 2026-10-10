import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getIdentity, logout } from '../src/api/auth';
vi.mock('../src/api/auth', () => ({
  getIdentity: vi.fn(),
  logout: vi.fn(),
}));
import { useAccountSettings } from '../src/components/settings/accountSettings';

const principal = { principal_id: 'admin', principal_type: 'user', roles: [], permissions: ['*'] };

describe('account settings controller', () => {
  beforeEach(() => {
    vi.mocked(getIdentity)
      .mockReset()
      .mockResolvedValue({ authentication_enabled: true, principal });
    vi.mocked(logout).mockReset().mockResolvedValue(undefined);
    const values = new Map<string, string>([['evernight.accessToken', 'session-token']]);
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => void values.set(key, value),
      removeItem: (key: string) => void values.delete(key),
    });
    vi.stubGlobal('window', { dispatchEvent: vi.fn() });
  });

  it('loads the signed-in identity', async () => {
    const account = useAccountSettings({ redirect: vi.fn() });

    await account.load();

    expect(account.identity.value?.principal?.principal_id).toBe('admin');
    expect(account.error.value).toBeNull();
  });

  it('reports a failed identity read', async () => {
    vi.mocked(getIdentity).mockRejectedValue(new Error('登录已失效，请重新登录。'));
    const account = useAccountSettings({ redirect: vi.fn() });

    await account.load();

    expect(account.identity.value).toBeNull();
    expect(account.error.value).toBe('登录已失效，请重新登录。');
  });

  it('ends the server session, clears the browser session, and opens the login page', async () => {
    const redirect = vi.fn();
    const account = useAccountSettings({ redirect });

    await account.signOut();

    expect(logout).toHaveBeenCalledOnce();
    expect(localStorage.getItem('evernight.accessToken')).toBeNull();
    expect(window.dispatchEvent).toHaveBeenCalledOnce();
    expect(redirect).toHaveBeenCalledExactlyOnceWith('./login.html');
  });

  it('still signs the browser out when the service rejects the logout', async () => {
    vi.mocked(logout).mockRejectedValue(new Error('offline'));
    const redirect = vi.fn();
    const account = useAccountSettings({ redirect });

    await account.signOut();

    expect(localStorage.getItem('evernight.accessToken')).toBeNull();
    expect(redirect).toHaveBeenCalledExactlyOnceWith('./login.html');
  });
});
