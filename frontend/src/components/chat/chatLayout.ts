import { ref } from 'vue'

export function useChatLayout() {
  const navigationOpen = ref(false)
  return {
    navigationOpen,
    openNavigation(): void { navigationOpen.value = true },
    closeNavigation(): void { navigationOpen.value = false },
  }
}
