import { computed } from 'vue'
import type { Session } from '../../api'
import { formatChatState } from './chatRequestStatus'

export type ChatHeaderProps = {
  session: Session | null
  state: string
  detailsOpen: boolean
}

export function useChatHeader(props: ChatHeaderProps) {
  return {
    title: computed(() => chatHeaderTitle(props.session)),
    stateLabel: computed(() => formatChatState(props.state)),
  }
}

export function chatHeaderTitle(session: Session | null): string {
  return session?.title || session?.session_id || '未选择会话'
}
