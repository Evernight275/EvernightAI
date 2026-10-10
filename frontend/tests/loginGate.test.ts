import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getAuthOptions, getIdentity } from '../src/api/auth';
vi.mock('../src/api/auth', () => ({
  getAuthOptions: vi.fn(),
  getIdentity: vi.fn(),
  login: vi.fn(),
}));
import { ApiError } from '../src/api/client';
import { loginRedirectTarget } from '../src/components/auth/loginForm';
import { loginPageFor } from '../src/components/auth/loginGate';

const principal = {
  principal_id: 'admin',
  principal_type: 'user',
  roles: [],
  permissions: ['*'],
};

function unauthorized(): ApiError {
  return new ApiError('Unauthorized', {
    status: 401,
    path: '/auth/me',
    requestId: null,
    errorType: null,
    detail: null,
  });
}

describe('login gate', () => {
  beforeEach(() => {
    vi.mocked(getAuthOptions)
      .mockReset()
      .mockResolvedValue({ authentication_enabled: true, login_enabled: true });
    vi.mocked(getIdentity).mockReset().mockRejectedValue(unauthorized());
  });

  it('sends a signed-out browser to the login page with a way back', async () => {
    const page = await loginPageFor('/chat.html?run=r1#images');

    expect(page).toBe('./login.html?redirect=%2Fchat.html%3Frun%3Dr1%23images');
    expect(loginRedirectTarget(page!.slice(page!.indexOf('?')))).toBe('/chat.html?run=r1#images');
  });

  it('uses the default destination when no target is given', async () => {
    expect(await loginPageFor()).toBe('./login.html');
  });

  it('lets a browser with an accepted credential through', async () => {
    vi.mocked(getIdentity).mockResolvedValue({ authentication_enabled: true, principal });

    expect(await loginPageFor('/chat.html')).toBeNull();
  });

  it('does not check identity when authentication is off', async () => {
    vi.mocked(getAuthOptions).mockResolvedValue({
      authentication_enabled: false,
      login_enabled: false,
    });

    expect(await loginPageFor('/chat.html')).toBeNull();
    expect(getIdentity).not.toHaveBeenCalled();
  });

  it('still sends a signed-out browser to the login page when password login is off', async () => {
    vi.mocked(getAuthOptions).mockResolvedValue({
      authentication_enabled: true,
      login_enabled: false,
    });

    expect(await loginPageFor()).toBe('./login.html');
  });

  it('surfaces an unreachable service to the caller', async () => {
    vi.mocked(getAuthOptions).mockRejectedValue(new TypeError('Failed to fetch'));

    await expect(loginPageFor('/chat.html')).rejects.toThrow('Failed to fetch');
  });
});
