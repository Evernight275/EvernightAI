import { createApp } from 'vue'
import App from './App.vue'
import { startWorkspaceRuntime } from './runtime/workspaceRuntime'
import './styles/base.css'

createApp(App).mount('#app')

const stopWorkspaceRuntime = startWorkspaceRuntime()

if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    stopWorkspaceRuntime()
  })
}
