import type { Session } from '../../api'

export function chatHeaderTitle(session: Session | null): string {
  return session?.title || session?.session_id || '未选择会话'
}
