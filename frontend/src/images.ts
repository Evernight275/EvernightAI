import { createApp } from 'vue';
import ImageApp from './ImageApp.vue';
import { startWorkspaceRuntime } from './runtime/workspaceRuntime';
import './styles/base.css';
import './styles/chat.css';
import './styles/images.css';
createApp(ImageApp).mount('#app');
const stop = startWorkspaceRuntime();
if (import.meta.hot) import.meta.hot.dispose(stop);
