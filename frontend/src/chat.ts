import { createApp } from 'vue'
import ChatApp from './ChatApp.vue'
import { startWorkspaceRuntime } from './runtime/workspaceRuntime'
import { chatActor } from './state/chatMachine'

createApp(ChatApp).mount('#app')

const stopWorkspaceRuntime = startWorkspaceRuntime()
chatActor.start()

if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    stopWorkspaceRuntime()
  })
}
