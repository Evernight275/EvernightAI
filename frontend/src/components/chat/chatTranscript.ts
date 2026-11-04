import { nextTick, onBeforeUnmount, ref, watch, type ComponentPublicInstance } from 'vue';
import type { ChatTranscriptEntry } from '../../domain/chat';

const waitingLabels: Record<string, string> = {
  preparing: '正在发送',
  streaming: '正在思考',
  evaluatingRun: '正在处理结果',
  resuming: '正在继续运行',
  retrying: '正在重试',
  recovering: '正在恢复运行进度',
};

// The reply has not visibly started yet: no streamed text and no running tool to watch.
export function chatWaitingLabel(state: string, entries: ChatTranscriptEntry[]): string | null {
  const label = waitingLabels[state];
  if (!label) return null;
  const last = entries.at(-1);
  if (last?.streaming && !last.toolActivity) return null;
  if (last?.toolActivity?.status === 'running') return null;
  return label;
}

export function useChatTranscript(entries: () => ChatTranscriptEntry[]) {
  const endMarker = ref<HTMLElement | null>(null);
  let scroller: HTMLElement | null = null;
  let following = true;
  const onScroll = (): void => {
    if (scroller)
      following = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 80;
  };
  watch(
    () => entries(),
    async (current, previous) => {
      const last = current.at(-1);
      const newUserMessage = last?.role === 'user' && last.entryId !== previous?.at(-1)?.entryId;
      const changedConversation = current[0]?.entryId !== previous?.[0]?.entryId;
      if (!following && !newUserMessage && !changedConversation) return;
      await nextTick();
      if (scroller) scroller.scrollTo({ top: scroller.scrollHeight, behavior: 'instant' });
    },
  );
  // Content can grow after an entry changes: spaced streaming updates, diagrams, images.
  const resize =
    typeof ResizeObserver === 'undefined'
      ? undefined
      : new ResizeObserver(() => {
          if (following && scroller)
            scroller.scrollTo({ top: scroller.scrollHeight, behavior: 'instant' });
        });
  onBeforeUnmount(() => {
    scroller?.removeEventListener('scroll', onScroll);
    resize?.disconnect();
  });
  return {
    setEndMarker(element: Element | ComponentPublicInstance | null): void {
      endMarker.value = element as HTMLElement | null;
      scroller?.removeEventListener('scroll', onScroll);
      resize?.disconnect();
      scroller = endMarker.value?.closest<HTMLElement>('.chat-view-scroll') || null;
      scroller?.addEventListener('scroll', onScroll, { passive: true });
      if (endMarker.value?.parentElement) resize?.observe(endMarker.value.parentElement);
    },
  };
}
