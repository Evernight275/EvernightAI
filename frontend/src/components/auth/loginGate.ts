import { getAuthOptions } from '../../api/auth';
import { isSignedIn } from './loginForm';

export const loginPath = './login.html';

/**
 * The login page a signed-out browser should open instead of `target`, or null
 * when the page may load.
 */
export async function loginPageFor(target?: string): Promise<string | null> {
  const authOptions = await getAuthOptions();
  if (!authOptions.authentication_enabled) return null;
  if (await isSignedIn()) return null;
  return target ? `${loginPath}?redirect=${encodeURIComponent(target)}` : loginPath;
}
