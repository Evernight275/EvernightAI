import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getAuthOptions, getIdentity } from '../src/api/auth';
import { getHealth, getReadiness } from '../src/api/health';
vi.mock('../src/api/auth', () => ({
  getAuthOptions: vi.fn(),
  getIdentity: vi.fn(),
  login: vi.fn(),
}));
vi.mock('../src/api/health', () => ({
  getHealth: vi.fn(),
  getReadiness: vi.fn(),
}));
import { ApiError } from '../src/api/client';
import { useServiceStatus } from '../src/components/status/serviceStatus';

const principal = {
  principal_id: 'admin',
  principal_type: 'user',
  roles: [],
  permissions: ['*'],
};

function useStatus() {
  const navigate = vi.fn();
  return { navigate, ...useServiceStatus({ navigate }) };
}

function apiError(status: number, message: string): ApiError {
  return new ApiError(message, {
    status,
    path: '/ready',
    requestId: null,
    errorType: null,
    detail: null,
  });
}

describe('service status controller', () => {
  beforeEach(() => {
    vi.mocked(getHealth).mockReset().mockResolvedValue({ status: 'ok' });
    vi.mocked(getReadiness).mockReset().mockResolvedValue({ status: 'ready' });
    vi.mocked(getAuthOptions)
      .mockReset()
      .mockResolvedValue({ authentication_enabled: true, login_enabled: true });
    vi.mocked(getIdentity).mockReset().mockRejectedValue(apiError(401, 'Unauthorized'));
  });

  it('reports a healthy and ready service', async () => {
    const status = useStatus();
    expect(status.state.value).toBe('checking');

    await status.check();

    expect(status.state.value).toBe('ready');
    expect(status.detail.value).toBeNull();
    expect(status.checkedTime.value).not.toBeNull();
    expect(status.busy.value).toBe(false);
  });

  it('reports a live service whose runtime is not ready', async () => {
    vi.mocked(getReadiness).mockRejectedValue(apiError(503, 'Runtime not ready'));
    const status = useStatus();

    await status.check();

    expect(status.state.value).toBe('starting');
    expect(status.detail.value).toBe('Runtime not ready（HTTP 503）');
  });

  it('reports an unreachable service without probing readiness', async () => {
    vi.mocked(getHealth).mockRejectedValue(new TypeError('Failed to fetch'));
    const status = useStatus();

    await status.check();

    expect(status.state.value).toBe('offline');
    expect(status.detail.value).toBe('无法连接服务，请确认服务已启动。');
    expect(getReadiness).not.toHaveBeenCalled();
  });

  it('recovers on the next check', async () => {
    vi.mocked(getHealth).mockRejectedValueOnce(new TypeError('Failed to fetch'));
    const status = useStatus();
    await status.check();

    await status.check();

    expect(status.state.value).toBe('ready');
    expect(status.detail.value).toBeNull();
  });

  it('sends a signed-out browser to the login page', async () => {
    const status = useStatus();

    await status.enter();

    expect(status.navigate).toHaveBeenCalledExactlyOnceWith('./login.html');
  });

  it('opens the control panel when a saved credential is accepted', async () => {
    vi.mocked(getIdentity).mockResolvedValue({ authentication_enabled: true, principal });
    const status = useStatus();

    await status.enter();

    expect(status.navigate).toHaveBeenCalledExactlyOnceWith('./chat.html');
  });

  it('stays on the page and reports when the service cannot be reached', async () => {
    vi.mocked(getAuthOptions).mockRejectedValue(new TypeError('Failed to fetch'));
    const status = useStatus();

    await status.enter();

    expect(status.navigate).not.toHaveBeenCalled();
    expect(status.enterError.value).toBe('无法连接服务，请确认服务已启动。');
    expect(status.entering.value).toBe(false);
  });
});
