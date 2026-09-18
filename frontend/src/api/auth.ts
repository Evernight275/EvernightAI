import { requestJson } from './client'

export type AuthSession = {
  authentication_enabled: boolean
  principal: {
    principal_id: string
    principal_type: string
    roles: string[]
    permissions: string[]
  } | null
}

export function getIdentity(credential?: { kind: 'api-key' | 'bearer'; value: string }): Promise<AuthSession> {
  return requestJson('/auth/me', credential ? {
    credentials: false,
    headers: credential.kind === 'bearer'
      ? { authorization: `Bearer ${credential.value.trim()}` }
      : { 'x-evernight-api-key': credential.value.trim() },
  } : {})
}
