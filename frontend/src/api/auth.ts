import { requestJson } from './client';

export type AuthSession = {
  authentication_enabled: boolean;
  login_enabled?: boolean;
  principal: {
    principal_id: string;
    principal_type: string;
    roles: string[];
    permissions: string[];
  } | null;
};

export function getIdentity(signal?: AbortSignal): Promise<AuthSession> {
  return requestJson('/auth/me', { signal });
}

export type AuthOptions = {
  authentication_enabled: boolean;
  login_enabled: boolean;
};

export function getAuthOptions(signal?: AbortSignal): Promise<AuthOptions> {
  return requestJson('/auth/config', { credentials: false, signal });
}

export type LoginSession = {
  access_token: string;
  token_type: string;
  expires_at: string;
  principal: NonNullable<AuthSession['principal']>;
};

export function login(
  username: string,
  password: string,
  signal?: AbortSignal,
): Promise<LoginSession> {
  return requestJson('/auth/login', {
    method: 'POST',
    body: { username, password },
    credentials: false,
    signal,
  });
}

export function logout(signal?: AbortSignal): Promise<void> {
  return requestJson('/auth/logout', { method: 'POST', signal });
}

export type ApiKeyInfo = {
  key_id: string;
  owner_id: string;
  name: string;
  prefix: string;
  created_at: string;
  expires_at: string | null;
  revoked_at: string | null;
};

export type IssuedApiKey = {
  api_key: string;
  key: ApiKeyInfo;
};

/** Keys are for scripts and integrations; the browser itself only signs in with a login session. */
export function listApiKeys(signal?: AbortSignal): Promise<ApiKeyInfo[]> {
  return requestJson('/auth/api-keys', { signal });
}

export function createApiKey(
  name: string,
  expiresAt: string | null = null,
  signal?: AbortSignal,
): Promise<IssuedApiKey> {
  return requestJson('/auth/api-keys', {
    method: 'POST',
    body: { name, expires_at: expiresAt },
    signal,
  });
}

export function revokeApiKey(keyId: string, signal?: AbortSignal): Promise<void> {
  return requestJson(`/auth/api-keys/${encodeURIComponent(keyId)}`, { method: 'DELETE', signal });
}
