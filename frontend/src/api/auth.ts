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

export function getIdentity(
  credential?: {
    kind: 'api-key' | 'bearer';
    value: string;
  },
  signal?: AbortSignal,
): Promise<AuthSession> {
  return requestJson(
    '/auth/me',
    credential
      ? {
          signal,
          credentials: false,
          headers:
            credential.kind === 'bearer'
              ? { authorization: `Bearer ${credential.value.trim()}` }
              : { 'x-evernight-api-key': credential.value.trim() },
        }
      : { signal },
  );
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
