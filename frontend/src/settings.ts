import { createApp } from 'vue';
import WorkspaceView from './components/workspace/WorkspaceView.vue';
import { startWorkspaceRuntime } from './runtime/workspaceRuntime';
import './styles/base.css';

createApp(WorkspaceView).mount('#app');

const stopWorkspaceRuntime = startWorkspaceRuntime();

if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    stopWorkspaceRuntime();
  });
}
