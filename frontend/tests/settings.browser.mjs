import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { chromium } from 'playwright';
const base = process.env.FRONTEND_URL || 'http://127.0.0.1:5173';
const screenshots = process.env.SCREENSHOT_DIR || '/tmp/evernight-layout';
await mkdir(screenshots, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
});
try {
  for (const width of [1440, 390, 320]) {
    const page = await browser.newPage({ viewport: { width, height: 844 } });
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.addInitScript(() => {
      window.EVERNIGHTAI_API_BASE = '/mock-api';
    });
    await page.route('**/mock-api/**', (route) => {
      if (route.request().url().endsWith('/auth/me')) {
        const headers = route.request().headers();
        if (headers.authorization !== 'Bearer test-token')
          return route.fulfill({ status: 401, json: { error: { message: 'Invalid credential' } } });
        return route.fulfill({
          json: {
            authentication_enabled: true,
            principal: {
              principal_id: 'browser-user',
              principal_type: 'user',
              roles: [],
              permissions: [],
            },
          },
        });
      }
      return route.fulfill({
        json: route.request().url().endsWith('/health') ? { status: 'ready' } : [],
      });
    });
    await page.goto(`${base}/chat.html`);
    await page.locator('#chat-message').fill('保留这份草稿');
    async function openSettings() {
      if (width <= 760) await page.getByRole('button', { name: '会话管理', exact: true }).click();
      await page.getByRole('button', { name: '设置', exact: true }).click();
      await page.locator('.settings-dialog').waitFor();
    }
    await openSettings();
    assert.ok(await page.locator('.settings-dialog').evaluate((el) => el.matches(':modal')));
    await page.screenshot({ path: `${screenshots}/${width}-settings-general.png` });
    await page.getByRole('button', { name: '连接与认证', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: '登录已失效' }).waitFor();
    // The browser signs in with an account only: no field accepts an API key.
    assert.equal(await page.locator('.settings-auth input').count(), 0);
    await page.evaluate(() => {
      localStorage.setItem('evernight.accessToken', 'test-token');
      window.dispatchEvent(new CustomEvent('evernight-access-token-change'));
    });
    await page.getByText('当前身份：browser-user', { exact: true }).waitFor();
    await page.getByRole('button', { name: '退出登录', exact: true }).waitFor();
    await page.screenshot({ path: `${screenshots}/${width}-settings-auth.png` });
    await page.getByRole('button', { name: '常规', exact: true }).click();
    await page.getByRole('button', { name: '管理账号', exact: true }).click();
    await page.getByText('当前身份：browser-user', { exact: true }).waitFor();
    assert.ok(
      await page.locator('.settings-shell').evaluate((el) => el.scrollWidth <= el.clientWidth),
    );
    assert.ok(
      await page
        .locator('.settings-shell')
        .evaluate((el) => el.getBoundingClientRect().bottom <= innerHeight),
    );
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => !document.querySelector('.settings-dialog').open);
    assert.equal(await page.locator('#chat-message').inputValue(), '');
    await page.locator('#chat-message').fill('退出后的新草稿');
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await openSettings();
    await page.getByText('当前身份：browser-user', { exact: true }).waitFor();
    assert.ok(
      await page
        .locator('.settings-dialog')
        .evaluate((el) => parseFloat(getComputedStyle(el).transitionDuration) < 0.001),
    );
    await page.getByRole('button', { name: '关闭设置', exact: true }).click();
    await page.waitForFunction(() => !document.querySelector('.settings-dialog').open);
    assert.equal(await page.locator('#chat-message').inputValue(), '退出后的新草稿');
    await page.goto(`${base}/settings.html`);
    await page.getByRole('button', { name: '连接与认证', exact: true }).click();
    await page.getByText('当前身份：browser-user', { exact: true }).waitFor();
    assert.equal(
      await page.getByRole('link', { name: '返回聊天', exact: true }).getAttribute('href'),
      '/chat.html',
    );
    assert.deepEqual(errors, []);
    console.log(
      `${width}px: settings navigation, account, close/Escape, draft preservation and standalone entry passed`,
    );
    await page.close();
  }
} finally {
  await browser.close();
}
