import { workspaceActor } from '../state/workspaceMachine'

export function startWorkspaceRuntime(): () => void {
  const notifyAuthChanged = () => workspaceActor.send({ type: 'AUTH_CHANGED' })
  window.addEventListener('evernight-api-key-change', notifyAuthChanged)
  window.addEventListener('evernight-access-token-change', notifyAuthChanged)

  workspaceActor.start()
  if (workspaceActor.getSnapshot().matches('idle')) {
    workspaceActor.send({ type: 'START' })
  }

  return () => {
    window.removeEventListener('evernight-api-key-change', notifyAuthChanged)
    window.removeEventListener('evernight-access-token-change', notifyAuthChanged)
  }
}
