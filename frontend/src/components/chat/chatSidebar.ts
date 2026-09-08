import { computed, onMounted, onUnmounted, ref, shallowRef, type ComputedRef } from 'vue'
import type { Session } from '../../api'
import type { ProviderCatalog } from '../../domain/workspace'
import {
  createChatContextId,
  createChatSessionId,
} from '../../runtime/chatRuntime'
import { chatActor } from '../../state/chatMachine'
import { workspaceActor } from '../../state/workspaceMachine'
import { useDialog } from '../common/dialog'

export function useSidebarDialog(props: { open: boolean }, close: () => void) {
  const compact = ref(false)
  let media: MediaQueryList | undefined
  const sync = (): void => { compact.value = media?.matches || false }
  onMounted(() => {
    media = window.matchMedia('(max-width: 760px)')
    sync()
    media.addEventListener('change', sync)
  })
  onUnmounted(() => media?.removeEventListener('change', sync))
  return useDialog(() => !compact.value || props.open, close, () => compact.value)
}

export type ChatSidebarItem = {
  id: string
  title: string
  status: string
  active: boolean
}

export function useChatSidebar(onNavigate: () => void = () => {}): {
  sessions: ComputedRef<ChatSidebarItem[]>
  newConversation: () => void
  selectSession: (sessionId: string) => void
} {
  const workspaceSnapshot = shallowRef(workspaceActor.getSnapshot())
  const chatSnapshot = shallowRef(chatActor.getSnapshot())
  const observedSessions = shallowRef<Session[]>([])
  const workspaceSubscription = workspaceActor.subscribe((snapshot) => {
    workspaceSnapshot.value = snapshot
  })
  const chatSubscription = chatActor.subscribe((snapshot) => {
    chatSnapshot.value = snapshot
    const session = snapshot.context.session
    if (session && !observedSessions.value.some(
      (item) => item.session_id === session.session_id,
    )) {
      observedSessions.value = [session, ...observedSessions.value]
    }
  })

  onUnmounted(() => {
    workspaceSubscription.unsubscribe()
    chatSubscription.unsubscribe()
  })

  return {
    sessions: computed(() => sidebarItems(
      mergeSessions(
        workspaceSnapshot.value.context.workspace.conversationIndex.sessions,
        observedSessions.value,
      ),
      chatSnapshot.value.context.session,
    )),
    newConversation(): void {
      chatActor.send({
        type: 'CREATE_SESSION',
        session: createChatSessionDraft(
          workspaceSnapshot.value.context.workspace.providerCatalog,
        ),
      })
      onNavigate()
    },
    selectSession(sessionId: string): void {
      const session = mergeSessions(
        workspaceSnapshot.value.context.workspace.conversationIndex.sessions,
        observedSessions.value,
      ).find((item) => item.session_id === sessionId)
      if (!session || session.session_id === chatSnapshot.value.context.session?.session_id) {
        onNavigate()
        return
      }
      chatActor.send({ type: 'SELECT_SESSION', session })
      onNavigate()
    },
  }
}

export function sidebarItems(
  sessions: Session[],
  activeSession: Session | null,
): ChatSidebarItem[] {
  const merged = mergeActiveSession(sessions, activeSession)
  return [...merged]
    .sort((left, right) => sessionCreatedTime(right) - sessionCreatedTime(left))
    .map((session) => ({
      id: session.session_id,
      title: session.title || session.session_id,
      status: session.status || 'active',
      active: session.session_id === activeSession?.session_id,
    }))
}

export function createChatSessionDraft(catalog: ProviderCatalog): Session {
  const provider = catalog.providers[0]
  const model = catalog.modelGroups.find(
    (group) => group.provider.provider_id === provider?.provider_id,
  )?.models[0]
  return {
    session_id: createChatSessionId(),
    context_id: createChatContextId(),
    title: '新会话',
    provider_id: provider?.provider_id || null,
    model_id: model?.model_id || null,
    status: 'active',
  }
}

function sessionCreatedTime(session: Session): number {
  const timestamp = session.created_at ? Date.parse(session.created_at) : 0
  return Number.isNaN(timestamp) ? 0 : timestamp
}

function mergeActiveSession(
  sessions: Session[],
  activeSession: Session | null,
): Session[] {
  if (!activeSession) {
    return sessions
  }
  const listedSession = sessions.find(
    (session) => session.session_id === activeSession.session_id,
  )
  if (!listedSession) {
    return [...sessions, activeSession]
  }
  return sessions.map((session) => (
    session.session_id === activeSession.session_id
      ? { ...listedSession, ...activeSession }
      : session
  ))
}

function mergeSessions(primary: Session[], secondary: Session[]): Session[] {
  return [
    ...primary,
    ...secondary.filter((session) => !primary.some(
      (item) => item.session_id === session.session_id,
    )),
  ]
}
