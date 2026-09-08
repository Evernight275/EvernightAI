import { nextTick, onBeforeUnmount, ref, watch, type ComponentPublicInstance } from 'vue'
import type { ChatTranscriptEntry } from '../../domain/chat'

export function useChatTranscript(entries: () => ChatTranscriptEntry[]) {
  const endMarker = ref<HTMLElement | null>(null)
  let scroller: HTMLElement | null = null
  let following = true
  const onScroll = (): void => {
    if (scroller) following = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 80
  }
  watch(() => entries(), async (current, previous) => {
    const last = current.at(-1)
    const newUserMessage = last?.role === 'user' && last.entryId !== previous?.at(-1)?.entryId
    const changedConversation = current[0]?.entryId !== previous?.[0]?.entryId
    if (!following && !newUserMessage && !changedConversation) return
    await nextTick()
    if (scroller) scroller.scrollTo({ top: scroller.scrollHeight, behavior: 'instant' })
  })
  onBeforeUnmount(() => scroller?.removeEventListener('scroll', onScroll))
  return {
    setEndMarker(element: Element | ComponentPublicInstance | null): void {
      endMarker.value = element as HTMLElement | null
      scroller?.removeEventListener('scroll', onScroll)
      scroller = endMarker.value?.closest<HTMLElement>('.chat-view-scroll') || null
      scroller?.addEventListener('scroll', onScroll, { passive: true })
    },
  }
}
