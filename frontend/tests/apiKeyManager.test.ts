import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createApiKey, listApiKeys, revokeApiKey, type ApiKeyInfo } from '../src/api/auth';
vi.mock('../src/api/auth', () => ({
  createApiKey: vi.fn(),
  listApiKeys: vi.fn(),
  revokeApiKey: vi.fn(),
}));
import { ApiError } from '../src/api/client';
import { apiKeyStatus, useApiKeyManager } from '../src/components/settings/apiKeyManager';

function key(overrides: Partial<ApiKeyInfo> = {}): ApiKeyInfo {
  return {
    key_id: 'k1',
    owner_id: 'admin',
    name: 'automation',
    prefix: 'ena_abcdefgh',
    created_at: '2026-01-01T00:00:00Z',
    expires_at: null,
    revoked_at: null,
    ...overrides,
  };
}

function apiError(status: number, message = 'failed'): ApiError {
  return new ApiError(message, {
    status,
    path: '/auth/api-keys',
    requestId: null,
    errorType: null,
    detail: null,
  });
}

describe('API key manager controller', () => {
  beforeEach(() => {
    vi.mocked(listApiKeys).mockReset().mockResolvedValue([key()]);
    vi.mocked(createApiKey)
      .mockReset()
      .mockResolvedValue({ api_key: 'ena_full-secret', key: key({ key_id: 'k2', name: 'ci' }) });
    vi.mocked(revokeApiKey).mockReset().mockResolvedValue(undefined);
  });

  it('lists the account keys for a login session', async () => {
    const manager = useApiKeyManager();
    expect(manager.access.value).toBe('loading');

    await manager.load();

    expect(manager.access.value).toBe('ready');
    expect(manager.keys.value).toEqual([key()]);
  });

  it('asks for account login when the credential is not a login session', async () => {
    vi.mocked(listApiKeys).mockRejectedValue(apiError(401));
    const manager = useApiKeyManager();

    await manager.load();

    expect(manager.access.value).toBe('login-required');
    expect(manager.error.value).toBeNull();
  });

  it('is unavailable when the service has no password login', async () => {
    vi.mocked(listApiKeys).mockRejectedValue(apiError(404));
    const manager = useApiKeyManager();

    await manager.load();

    expect(manager.access.value).toBe('unavailable');
    expect(manager.error.value).toBeNull();
  });

  it('issues a key, keeps the secret for one display, and refreshes the list', async () => {
    const manager = useApiKeyManager();
    await manager.load();
    manager.name.value = '  ci  ';
    manager.expiresAt.value = '2030-01-02T03:04';

    await manager.create();

    expect(createApiKey).toHaveBeenCalledWith('ci', new Date('2030-01-02T03:04').toISOString());
    expect(manager.issued.value?.api_key).toBe('ena_full-secret');
    expect(manager.name.value).toBe('');
    expect(manager.expiresAt.value).toBe('');
    expect(listApiKeys).toHaveBeenCalledTimes(2);

    manager.dismissIssued();
    expect(manager.issued.value).toBeNull();
  });

  it('sends no expiry when none is chosen and ignores a blank name', async () => {
    const manager = useApiKeyManager();
    await manager.load();

    manager.name.value = '   ';
    await manager.create();
    expect(createApiKey).not.toHaveBeenCalled();

    manager.name.value = 'ci';
    await manager.create();
    expect(createApiKey).toHaveBeenCalledWith('ci', null);
  });

  it('keeps the form and reports the server message when issuing fails', async () => {
    vi.mocked(createApiKey).mockRejectedValue(
      apiError(400, 'API key expiry must be in the future'),
    );
    const manager = useApiKeyManager();
    await manager.load();
    manager.name.value = 'ci';

    await manager.create();

    expect(manager.error.value).toBe('API key expiry must be in the future');
    expect(manager.name.value).toBe('ci');
    expect(manager.issued.value).toBeNull();
    expect(manager.access.value).toBe('ready');
  });

  it('revokes only after confirmation and drops the matching one-time secret', async () => {
    const manager = useApiKeyManager();
    await manager.load();
    manager.name.value = 'ci';
    await manager.create();

    await manager.revoke();
    expect(revokeApiKey).not.toHaveBeenCalled();

    manager.pendingRevoke.value = key({ key_id: 'k2', name: 'ci' });
    await manager.revoke();

    expect(revokeApiKey).toHaveBeenCalledExactlyOnceWith('k2');
    expect(manager.pendingRevoke.value).toBeNull();
    expect(manager.issued.value).toBeNull();
  });

  it('falls back to the login prompt when the session ends mid-use', async () => {
    const manager = useApiKeyManager();
    await manager.load();
    vi.mocked(revokeApiKey).mockRejectedValue(apiError(401));
    manager.pendingRevoke.value = key();

    await manager.revoke();

    expect(manager.access.value).toBe('login-required');
    expect(manager.pendingRevoke.value).toBeNull();
  });

  it('classifies keys as active, expired, or revoked', () => {
    const now = new Date('2026-06-01T00:00:00Z');

    expect(apiKeyStatus(key(), now)).toBe('active');
    expect(apiKeyStatus(key({ expires_at: '2026-07-01T00:00:00Z' }), now)).toBe('active');
    expect(apiKeyStatus(key({ expires_at: '2026-05-01T00:00:00Z' }), now)).toBe('expired');
    expect(
      apiKeyStatus(
        key({ expires_at: '2026-05-01T00:00:00Z', revoked_at: '2026-04-01T00:00:00Z' }),
        now,
      ),
    ).toBe('revoked');
  });
});
