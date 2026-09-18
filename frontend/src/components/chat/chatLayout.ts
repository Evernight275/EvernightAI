import { ref } from 'vue'

export function useChatLayout() {
  const navigationOpen = ref(false)
  const sidebarCollapsed = ref(false)
  return {
    navigationOpen,
    sidebarCollapsed,
    openNavigation(): void {
      sidebarCollapsed.value = false
      navigationOpen.value = true
    },
    closeNavigation(): void { navigationOpen.value = false },
    collapseSidebar(): void {
      sidebarCollapsed.value = true
      navigationOpen.value = false
    },
  }
}
