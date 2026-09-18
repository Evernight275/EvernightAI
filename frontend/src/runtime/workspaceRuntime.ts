import { workspaceActor } from '../state/workspaceMachine'
import { chatActor } from '../state/chatMachine'
import { ref } from 'vue'
import { clearWorkingDirectory } from './workingDirectory'

export const authGeneration = ref(0)

export function startWorkspaceRuntime(): () => void {
  const notifyAuthChanged = () => {
    clearWorkingDirectory()
    chatActor.send({ type: 'AUTH_CHANGED' })
    workspaceActor.send({ type: 'AUTH_CHANGED' })
    authGeneration.value += 1
  }
  const notifyStorageChanged = (event: StorageEvent) => {
    if (event.key === null || ['evernight.apiKey', 'evernight.accessToken', 'evernight.signedOut'].includes(event.key)) notifyAuthChanged()
  }
  window.addEventListener('storage', notifyStorageChanged)
  window.addEventListener('evernight-api-key-change', notifyAuthChanged)
  window.addEventListener('evernight-access-token-change', notifyAuthChanged)

  workspaceActor.start()
  if (workspaceActor.getSnapshot().matches('idle')) {
    workspaceActor.send({ type: 'START' })
  }

  return () => {
    window.removeEventListener('storage', notifyStorageChanged)
    window.removeEventListener('evernight-api-key-change', notifyAuthChanged)
    window.removeEventListener('evernight-access-token-change', notifyAuthChanged)
  }
}
