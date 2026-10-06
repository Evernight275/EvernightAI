import assert from 'node:assert/strict';
import { chromium } from 'playwright';
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
});
try {
  for (const platform of ['linux', 'windows']) {
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
      const separator = platform === 'windows' ? '\\' : '/';
      const root = platform === 'windows' ? 'C:\\' : '/home/user';
      const join = (parent, name) => `${parent.replace(/[\\/]$/, '')}${separator}${name}`;
      const service = join(root, 'EvernightAI');
      const workspace = join(service, 'workspaces');
      const project = join(workspace, 'project');
      const createdPath = join(project, 'new');
      const projects = join(root, 'projects');
      const external = join(projects, 'existing-project');
      const src = join(external, 'src');
      const registered = new Set([workspace]);
      let created = false;
      const registrations = [];
      const children = new Map([
        [root, [service, projects]],
        [service, [workspace]],
        [workspace, [project]],
        [projects, [external]],
        [external, [src]],
      ]);
      const listing = (path) => {
        if (path === '.') path = root;
        if (platform === 'windows') path = path.replaceAll('/', separator);
        const boundary = platform === 'windows' && path.startsWith('D:') ? 'D:\\' : root;
        const parent =
          path === boundary ? null : path.slice(0, path.lastIndexOf(separator)) || boundary;
        return {
          root: boundary,
          path,
          parent: parent === 'C:' || parent === 'D:' ? `${parent}\\` : parent,
          truncated: false,
          requires_registration: ![...registered].some(
            (item) => path === item || path.startsWith(`${item}${separator}`),
          ),
          entries: [
            ...(path === project && created ? [createdPath] : children.get(path) || []).map(
              (entry) => ({ name: entry.split(separator).at(-1), path: entry, is_directory: true }),
            ),
            ...(path === workspace
              ? [{ name: 'README.md', path: join(workspace, 'README.md'), is_directory: false }]
              : []),
          ],
        };
      };
      await page.route('**/mock-api/**', (route) => {
        const url = new URL(route.request().url());
        if (url.pathname.endsWith('/workspaces/projects')) {
          if (route.request().method() === 'POST') {
            const { path } = route.request().postDataJSON();
            if (path === '/missing')
              return route.fulfill({
                status: 404,
                json: { error: { message: '项目文件夹不存在' } },
              });
            if (path === root)
              return route.fulfill({
                status: 400,
                json: {
                  error: { message: '此目录包含服务数据或运行环境，请选择独立的项目文件夹' },
                },
              });
            registrations.push(path);
            registered.add(path);
            return route.fulfill({ status: 201, json: listing(path) });
          }
          return route.fulfill({
            json: [...registered].map((path) => ({ name: path.split(separator).at(-1), path })),
          });
        }
        if (url.pathname.endsWith('/workspaces')) {
          if (route.request().method() === 'POST') {
            const body = route.request().postDataJSON();
            assert.equal(body.path, project);
            if (body.name === 'duplicate')
              return route.fulfill({ status: 409, json: { error: { message: '此名称已存在' } } });
            assert.equal(body.name, 'new');
            created = true;
            return route.fulfill({ status: 201, json: listing(createdPath) });
          }
          return route.fulfill({ json: listing(url.searchParams.get('path')) });
        }
        return route.fulfill({ json: url.pathname.endsWith('/health') ? { status: 'ok' } : [] });
      });
      await page.goto('http://127.0.0.1:5173/chat.html');
      const open = async () => {
        if (width <= 760) await page.getByRole('button', { name: '会话管理', exact: true }).click();
        await page.getByRole('button', { name: '选择工作文件夹' }).click();
      };
      const parentButton = page.getByRole('button', { name: '上一级文件夹' });
      const chooseButton = page.getByRole('button', { name: '使用此文件夹' });
      const saved = () =>
        page.evaluate(() => JSON.parse(localStorage.getItem('evernight.workingDirectory')));
      await open();
      await page.getByRole('button', { name: 'EvernightAI', exact: true }).waitFor();
      assert.equal(await parentButton.isDisabled(), true);
      await chooseButton.click();
      await page.getByRole('alert').filter({ hasText: '请选择独立的项目文件夹' }).waitFor();
      await page.getByRole('button', { name: 'EvernightAI', exact: true }).click();
      await page.getByRole('button', { name: 'workspaces', exact: true }).click();
      await page.getByText('README.md', { exact: true }).waitFor();
      assert.equal(await parentButton.isDisabled(), false);
      await page.getByRole('button', { name: 'project', exact: true }).click();
      await page.getByRole('button', { name: '新建', exact: true }).click();
      await page.getByLabel('新文件夹名称').fill('duplicate');
      await page.getByRole('button', { name: '创建文件夹', exact: true }).click();
      await page.getByRole('alert').filter({ hasText: '此名称已存在' }).waitFor();
      await page.getByLabel('新文件夹名称').fill('new');
      await page.getByRole('button', { name: '创建文件夹', exact: true }).click();
      await page
        .locator('.workspace-picker-toolbar strong')
        .filter({ hasText: createdPath })
        .waitFor();
      await chooseButton.click();
      await page.locator('.workspace-picker-dialog').waitFor({ state: 'hidden' });
      assert.equal((await saved()).path, createdPath);
      assert.deepEqual(registrations, []);
      await page.reload();
      await open();
      await page
        .locator('.workspace-picker-toolbar strong')
        .filter({ hasText: createdPath })
        .waitFor();
      await parentButton.click();
      await page.getByRole('button', { name: 'new', exact: true }).waitFor();
      await parentButton.click();
      await page.getByText('README.md', { exact: true }).waitFor();
      await parentButton.click();
      await page.getByRole('button', { name: 'workspaces', exact: true }).waitFor();
      await parentButton.click();
      await page.getByRole('button', { name: 'projects', exact: true }).waitFor();
      assert.equal(await parentButton.isDisabled(), true);
      await page.getByRole('button', { name: 'projects', exact: true }).click();
      await page.getByRole('button', { name: 'existing-project', exact: true }).click();
      await page.getByRole('button', { name: 'src', exact: true }).waitFor();
      assert.equal(await parentButton.isDisabled(), false);
      await chooseButton.click();
      await page.locator('.workspace-picker-dialog').waitFor({ state: 'hidden' });
      assert.equal((await saved()).path, external);
      assert.deepEqual(registrations, [external]);
      await page.reload();
      await open();
      await page.getByRole('button', { name: 'src', exact: true }).waitFor();
      await page.getByLabel('已添加项目').selectOption(workspace);
      await page.getByText('README.md', { exact: true }).waitFor();
      await page.getByLabel('现有项目路径').fill('/missing');
      await page.getByRole('button', { name: '添加并打开' }).click();
      await page.getByRole('alert').filter({ hasText: '项目文件夹不存在' }).waitFor();
      await page.getByLabel('现有项目路径').fill(external);
      await page.getByRole('button', { name: '添加并打开' }).click();
      await page.locator('.workspace-picker-dialog').waitFor({ state: 'hidden' });
      assert.equal((await saved()).path, external);
      // Restore the relative path saved by the previous browser version.
      await page.evaluate(
        ({ workspace }) => {
          localStorage.setItem(
            'evernight.workingDirectory',
            JSON.stringify({ root: workspace, path: 'project/new' }),
          );
        },
        { workspace },
      );
      await page.reload();
      await open();
      await page
        .locator('.workspace-picker-toolbar strong')
        .filter({ hasText: createdPath })
        .waitFor();
      if (platform === 'windows') {
        await page.getByLabel('现有项目路径').fill('D:\\other-project');
        await page.getByRole('button', { name: '添加并打开' }).click();
        await page
          .getByRole('button', { name: '选择工作文件夹' })
          .filter({ hasText: 'other-project' })
          .waitFor();
        await page.getByRole('button', { name: '选择工作文件夹' }).click();
        await parentButton.click();
        await page
          .locator('.workspace-picker-toolbar strong')
          .filter({ hasText: '根目录' })
          .waitFor();
        assert.equal(await parentButton.isDisabled(), true);
        assert.equal(await page.locator('.workspace-root').textContent(), 'D:\\');
      }
      assert.ok(
        await page
          .locator('.workspace-picker-dialog')
          .evaluate((el) => el.scrollWidth <= el.clientWidth),
      );
      assert.deepEqual(errors, []);
      await page.close();
      console.log(
        `${platform} ${width}px: browse parents, register selection, create, restore passed`,
      );
    }
  }
} finally {
  await browser.close();
}
