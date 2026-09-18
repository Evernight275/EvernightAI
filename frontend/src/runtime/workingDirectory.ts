import { ref } from 'vue'

export const workingDirectory = ref<string | undefined>()
export const workingRoot = ref('')
export function clearWorkingDirectory(): void {
  workingDirectory.value = undefined
  workingRoot.value = ''
  localStorage.removeItem('evernight.workingDirectory')
}
