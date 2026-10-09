import { onMounted, onUnmounted, ref } from 'vue';
import { useDialog } from '../common/dialog';

export function useChatLayout() {
  const navigationOpen = ref(false);
  const sidebarCollapsed = ref(false);
  return {
    navigationOpen,
    sidebarCollapsed,
    openNavigation(): void {
      sidebarCollapsed.value = false;
      navigationOpen.value = true;
    },
    closeNavigation(): void {
      navigationOpen.value = false;
    },
    collapseSidebar(): void {
      sidebarCollapsed.value = true;
      navigationOpen.value = false;
    },
  };
}

export function useSidebarDialog(props: { open: boolean; collapsed?: boolean }, close: () => void) {
  const compact = ref(false);
  let media: MediaQueryList | undefined;
  const sync = (): void => {
    compact.value = media?.matches || false;
  };
  onMounted(() => {
    media = window.matchMedia('(max-width: 760px)');
    sync();
    media.addEventListener('change', sync);
  });
  onUnmounted(() => media?.removeEventListener('change', sync));
  return useDialog(
    () => (compact.value ? props.open : !props.collapsed),
    close,
    () => compact.value,
  );
}
