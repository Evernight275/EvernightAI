import { createApp } from 'vue'
import ChatApp from './ChatApp.vue'
import { startWorkspaceRuntime } from './runtime/workspaceRuntime'
import { chatActor } from './state/chatMachine'
import 'katex/dist/katex.min.css'
import './styles/base.css'
import './styles/chat.css'

createApp(ChatApp).mount('#app')

const stopWorkspaceRuntime = startWorkspaceRuntime()
chatActor.start()

if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    stopWorkspaceRuntime()
  })
}
