import { computed, ref } from 'vue';
import { ApiError } from '../../api/client';
import { getHealth, getReadiness } from '../../api/health';
import { loginPageFor } from '../auth/loginGate';

export const controlPanelPath = './chat.html';

export type ServiceStatusOptions = {
  navigate: (target: string) => void;
};

export type ServiceState = 'checking' | 'ready' | 'starting' | 'offline';

export function useServiceStatus(options: ServiceStatusOptions) {
  const state = ref<ServiceState>('checking');
  const detail = ref<string | null>(null);
  const checkedAt = ref<Date | null>(null);
  const busy = ref(false);
  const entering = ref(false);
  const enterError = ref<string | null>(null);
  const stateLabel = computed(
    () =>
      ({
        checking: '检查中',
        ready: '运行正常',
        starting: '服务已启动，运行时未就绪',
        offline: '服务不可用',
      })[state.value],
  );
  const checkedTime = computed(
    () => checkedAt.value?.toLocaleString('zh-CN', { hour12: false }) ?? null,
  );

  /** Reads only the unauthenticated probes, so the page needs no credentials. */
  async function check(): Promise<void> {
    if (busy.value) return;
    busy.value = true;
    try {
      await getHealth();
      try {
        await getReadiness();
        state.value = 'ready';
        detail.value = null;
      } catch (error) {
        state.value = 'starting';
        detail.value = errorMessage(error);
      }
    } catch (error) {
      state.value = 'offline';
      detail.value = errorMessage(error);
    }
    checkedAt.value = new Date();
    busy.value = false;
  }

  /** Opens the control panel, or the login page when this browser is not signed in. */
  async function enter(): Promise<void> {
    if (entering.value) return;
    entering.value = true;
    enterError.value = null;
    try {
      options.navigate((await loginPageFor()) ?? controlPanelPath);
    } catch (error) {
      enterError.value = errorMessage(error);
    }
    entering.value = false;
  }

  return { state, stateLabel, detail, checkedTime, busy, check, entering, enterError, enter };
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return `${error.message}（HTTP ${error.status}）`;
  return '无法连接服务，请确认服务已启动。';
}
