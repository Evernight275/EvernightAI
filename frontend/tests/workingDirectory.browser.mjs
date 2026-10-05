import assert from 'node:assert/strict';
import { chromium } from 'playwright';
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
});
try {
  for (const width of [1440, 390, 320]) {
    const page = await browser.newPage({
      viewport: { width, height: 844 },
      reducedMotion: 'reduce',
    });
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.addInitScript(() => {
      window.EVERNIGHTAI_API_BASE = '/mock-api';
    });
    let created = false;
    let added = false;
    const external = '/home/projects/existing-project';
    const listing = (path) =>
      path.startsWith(external)
        ? {
            root: external,
            path,
            truncated: false,
            parent: path === external ? null : external,
            entries:
              path === external
                ? [{ name: 'src', path: `${external}/src`, is_directory: true }]
                : [],
          }
        : {
            root: '/workspace',
            path,
            truncated: false,
            entries:
              path === '.'
                ? [
                    { name: 'project', path: 'project', is_directory: true },
                    { name: 'README.md', path: 'README.md', is_directory: false },
                  ]
                : path === 'project' && created
                  ? [{ name: 'new', path: 'project/new', is_directory: true }]
                  : [],
          };
    await page.route('**/mock-api/**', (route) => {
      const url = new URL(route.request().url());
      if (url.pathname.endsWith('/workspaces/projects')) {
        if (route.request().method() === 'POST') {
          const { path } = route.request().postDataJSON();
          if (path !== external)
            return route.fulfill({ status: 404, json: { error: { message: '项目文件夹不存在' } } });
          added = true;
          return route.fulfill({ status: 201, json: listing(external) });
        }
        return route.fulfill({
          json: [
            { name: '默认目录', path: '/workspace' },
            ...(added ? [{ name: 'existing-project', path: external }] : []),
          ],
        });
      }
      if (url.pathname.endsWith('/workspaces')) {
        if (route.request().method() === 'POST') {
          const body = route.request().postDataJSON();
          assert.equal(body.path, 'project');
          if (body.name === 'duplicate')
            return route.fulfill({ status: 409, json: { error: { message: '此名称已存在' } } });
          assert.equal(body.name, 'new');
          created = true;
          return route.fulfill({ status: 201, json: listing('project/new') });
        }
        const path = url.searchParams.get('path');
        return route.fulfill({ json: listing(path === '/workspace' ? '.' : path) });
      }
      return route.fulfill({ json: url.pathname.endsWith('/health') ? { status: 'ok' } : [] });
    });
    await page.goto('http://127.0.0.1:5173/chat.html');
    const open = async () => {
      if (width <= 760) await page.getByRole('button', { name: '会话管理', exact: true }).click();
      await page.getByRole('button', { name: '选择工作文件夹' }).click();
    };
    await open();
    await page.getByText('README.md', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'project', exact: true }).click();
    await page.getByText('此文件夹为空，可以作为新的工作目录。').waitFor();
    await page.getByRole('button', { name: '新建', exact: true }).click();
    await page.getByLabel('新文件夹名称').fill('duplicate');
    await page.getByRole('button', { name: '创建文件夹', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: '此名称已存在' }).waitFor();
    await page.getByLabel('新文件夹名称').fill('new');
    await page.getByRole('button', { name: '创建文件夹', exact: true }).click();
    await page
      .locator('.workspace-picker-toolbar strong')
      .filter({ hasText: 'project/new' })
      .waitFor();
    await page.screenshot({ path: `/tmp/evernight-layout/${width}-working-directory.png` });
    assert.ok(
      await page
        .locator('.workspace-picker-dialog')
        .evaluate((el) => el.scrollWidth <= el.clientWidth),
    );
    await page.getByRole('button', { name: '使用此文件夹' }).click();
    assert.equal(
      await page.evaluate(
        () => JSON.parse(localStorage.getItem('evernight.workingDirectory')).path,
      ),
      'project/new',
    );
    await page.reload();
    if (width <= 760) await page.getByRole('button', { name: '会话管理', exact: true }).click();
    await page.getByRole('button', { name: '选择工作文件夹' }).filter({ hasText: 'new' }).waitFor();
    await page.getByRole('button', { name: '选择工作文件夹' }).click();
    await page.getByRole('button', { name: '上一级文件夹' }).click();
    await page.getByRole('button', { name: 'new', exact: true }).waitFor();
    await page.getByRole('button', { name: '使用此文件夹' }).click();
    assert.equal(
      await page.evaluate(
        () => JSON.parse(localStorage.getItem('evernight.workingDirectory')).path,
      ),
      'project',
    );
    await page.getByRole('button', { name: '选择工作文件夹' }).click();
    await page.getByLabel('现有项目路径').fill('/missing');
    await page.getByRole('button', { name: '添加并打开' }).click();
    await page.getByRole('alert').filter({ hasText: '项目文件夹不存在' }).waitFor();
    await page.getByLabel('现有项目路径').fill(external);
    await page.getByRole('button', { name: '添加并打开' }).click();
    await page
      .getByRole('button', { name: '选择工作文件夹' })
      .filter({ hasText: 'existing-project' })
      .waitFor();
    assert.equal(
      await page.getByRole('button', { name: '选择工作文件夹' }).getAttribute('title'),
      external,
    );
    await page.reload();
    if (width <= 760) await page.getByRole('button', { name: '会话管理', exact: true }).click();
    await page
      .getByRole('button', { name: '选择工作文件夹' })
      .filter({ hasText: 'existing-project' })
      .waitFor();
    await page.getByRole('button', { name: '选择工作文件夹' }).click();
    await page.getByRole('button', { name: 'src', exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: '上一级文件夹' }).isDisabled(), true);
    await page.getByLabel('已添加项目').selectOption('/workspace');
    await page.getByText('README.md', { exact: true }).waitFor();
    await page.getByLabel('已添加项目').selectOption(external);
    await page.getByRole('button', { name: 'src', exact: true }).click();
    await page.getByRole('button', { name: '上一级文件夹' }).click();
    await page.getByRole('button', { name: 'src', exact: true }).waitFor();
    await page.screenshot({ path: `/tmp/evernight-layout/${width}-external-project.png` });
    assert.ok(
      await page
        .locator('.workspace-picker-dialog')
        .evaluate((el) => el.scrollWidth <= el.clientWidth),
    );
    await page.getByRole('button', { name: '使用此文件夹' }).click();
    assert.equal(
      await page.evaluate(
        () => JSON.parse(localStorage.getItem('evernight.workingDirectory')).path,
      ),
      external,
    );
    assert.deepEqual(errors, []);
    await page.close();
    console.log(`${width}px: directory browse/create/conflict/switch/restore passed`);
  }
} finally {
  await browser.close();
}
