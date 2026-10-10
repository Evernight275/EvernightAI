import { createApp } from 'vue';
import ChatApp from './ChatApp.vue';
import { loginPageFor } from './components/auth/loginGate';
import { startWorkspaceRuntime } from './runtime/workspaceRuntime';
import { chatActor } from './state/chatMachine';
import 'katex/dist/katex.min.css';
import './styles/base.css';
import './styles/chat.css';
import './styles/images.css';
import './styles/data.css';

let stopWorkspaceRuntime = () => {};

async function start(): Promise<void> {
  const { pathname, search, hash } = window.location;
  // An unreachable service still opens the chat, which reports the outage itself.
  const loginPage = await loginPageFor(pathname + search + hash).catch(() => null);
  if (loginPage) {
    window.location.replace(loginPage);
    return;
  }
  createApp(ChatApp).mount('#app');
  stopWorkspaceRuntime = startWorkspaceRuntime();
  chatActor.start();
}

void start();

if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    stopWorkspaceRuntime();
  });
}
