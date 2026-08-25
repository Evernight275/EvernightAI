import { nextTick, ref, watch, type ComponentPublicInstance } from 'vue'
import type { ChatTranscriptEntry } from '../../domain/chat'

export function useChatTranscript(
  entries: () => ChatTranscriptEntry[],
): {
  setEndMarker: (element: Element | ComponentPublicInstance | null) => void
} {
  const endMarker = ref<HTMLElement | null>(null)

  watch(
    () => entries().length,
    async (length, previousLength) => {
      if (length === 0 || length === previousLength) {
        return
      }
      await nextTick()
      endMarker.value?.scrollIntoView({ block: 'end' })
    },
  )

  return {
    setEndMarker(element): void {
      endMarker.value = element as HTMLElement | null
    },
  }
}
