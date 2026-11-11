import { test, expect, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
const credentials = JSON.parse(
  readFileSync('/tmp/management-depth-credentials.json', 'utf8'),
)
const output = resolve(
  process.env.MANAGEMENT_SCREENSHOT_DIR || '../../../output/management-upgrade',
)
mkdirSync(output, { recursive: true })
const suffix = '?database=warehouse&companyId=100'
test.afterEach(async ({ page }) => {
  await page.locator('input[type=password]').evaluateAll((inputs) =>
    inputs.forEach((input) => {
      ;(input as HTMLInputElement).value = ''
    }),
  )
})
async function login(page: Page) {
  await page.goto('/management/login')
  await page.getByLabel('密码', { exact: true }).fill(credentials.password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: '数据源', exact: true }),
  ).toBeVisible()
}

test('发现、跨页选择、字段预览、保存响应丢失核对与发布', async ({ page }) => {
  const exceptions: string[] = []
  page.on('pageerror', (error) => exceptions.push(error.message))
  await login(page)
  const sourceId = 'access-e2e-' + Date.now(),
    api = '/management/api/v1/sources/' + sourceId
  const me = await (await page.request.get('/management/api/v1/me')).json()
  const created = await page.request.post('/management/api/v1/sources', {
    headers: { origin: 'http://127.0.0.1:7789', 'x-csrf-token': me.csrfToken },
    data: {
      scopeDatabase: 'warehouse',
      companyId: '100',
      sourceId,
      name: '表范围闭环验收',
      type: 'starrocks',
      database: 'warehouse',
      dsn: 'starrocks://reader:isolated@localhost:9030/warehouse',
      reportingProfileVersionId: 'base:1',
    },
  })
  expect(created.status()).toBe(201)
  await page.goto('/management/sources/' + sourceId + suffix + '&tab=tables')
  await page
    .getByRole('button', { name: '刷新数据库目录', exact: true })
    .click()
  await expect(page.getByText('共 56 个匹配对象')).toBeVisible()
  await page
    .getByRole('button', { name: 'warehouse.orders', exact: true })
    .click()
  await expect(page.getByRole('dialog')).toContainText('DECIMAL(18,2)')
  await page.getByRole('button', { name: '关闭', exact: true }).click()
  await page.getByRole('button', { name: '选择本页', exact: true }).click()
  await expect(page.getByText('已选 25 / 200')).toBeVisible()
  await page.getByRole('button', { name: '下一页', exact: true }).click()
  await page.getByRole('button', { name: '选择本页', exact: true }).click()
  await expect(page.getByText('已选 50 / 200')).toBeVisible()
  await page.getByRole('button', { name: '取消选择本页', exact: true }).click()
  await expect(page.getByText('已选 25 / 200')).toBeVisible()
  await page.getByLabel('搜索表', { exact: true }).fill('view_orders')
  await expect(page.getByText('共 1 个匹配对象')).toBeVisible()
  await page.getByRole('button', { name: '选择本页', exact: true }).click()
  await expect(page.getByText('已选 26 / 200')).toBeVisible()
  await expect(
    page.getByRole('button', { name: '发布', exact: true }),
  ).toBeDisabled()
  await page.getByLabel('搜索表', { exact: true }).fill('')
  await page.getByText('只看已选', { exact: true }).click()
  await page.locator('.ant-pagination-next').click()
  await page.getByRole('button', { name: '取消选择本页', exact: true }).click()
  await expect(page.getByText('已选 25 / 200')).toBeVisible()
  await page.getByRole('button', { name: '取消选择本页', exact: true }).click()
  await expect(page.getByText('已选 0 / 200')).toBeVisible()
  await expect(
    page.getByRole('button', { name: '保存表范围', exact: true }),
  ).toBeDisabled()
  await page.getByText('只看已选', { exact: true }).click()
  await page.getByRole('button', { name: '选择本页', exact: true }).click()
  await page.getByLabel('搜索表', { exact: true }).fill('view_orders')
  await expect(page.getByText('共 1 个匹配对象')).toBeVisible()
  await page.getByRole('button', { name: '选择本页', exact: true }).click()
  await expect(page.getByText('已选 26 / 200')).toBeVisible()
  // 服务器真实提交成功后丢弃响应，必须先读取版本和实际范围，不自动重试。
  let writes = 0
  await page.route('**' + api + '/table-access', async (route) => {
    if (route.request().method() !== 'PUT') return route.continue()
    writes++
    await route.fetch()
    await route.abort('failed')
  })
  await page.getByRole('button', { name: '保存表范围', exact: true }).click()
  await expect(
    page.getByText(
      '提交结果待确认；请读取最新版本和实际选择，核对后再决定，不会自动重试。',
    ),
  ).toBeVisible()
  await expect(
    page.getByRole('button', { name: '保存表范围', exact: true }),
  ).toBeDisabled()
  await page
    .getByRole('button', { name: '读取最新范围并核对', exact: true })
    .click()
  await expect(
    page.getByRole('dialog', { name: '核对服务器范围与本地选择' }),
  ).toContainText('服务器草稿 v2')
  await page
    .getByRole('button', { name: '采用服务器范围', exact: true })
    .click()
  expect(writes).toBe(1)
  await page.unroute('**' + api + '/table-access')
  await page.screenshot({
    path: resolve(output, 'tables-1440.png'),
    fullPage: true,
  })
  await page.getByRole('button', { name: '发布', exact: true }).click()
  await expect(
    page.getByRole('dialog', { name: '确认发布数据源' }),
  ).toContainText('发布后 26 张')
  await page.screenshot({
    path: resolve(output, 'release-1440.png'),
    fullPage: true,
  })
  await page.getByRole('button', { name: '确认发布', exact: true }).click()
  await expect(
    page.getByRole('dialog', { name: '确认发布数据源' }),
  ).toBeHidden()
  const state = await (
    await page.request.get(
      api + '/table-access?scopeDatabase=warehouse&companyId=100',
    )
  ).json()
  expect(state.draftVersion).toBe(2)
  expect(state.publishedTables).toHaveLength(26)
  writeFileSync(
    resolve(output, 'http-publication.json'),
    JSON.stringify(
      {
        draftVersion: state.draftVersion,
        publishedTables: state.publishedTables,
        writes,
      },
      null,
      2,
    ),
  )
  expect(exceptions).toEqual([])
})

test('1440/1280/768/390布局、焦点与关键页面axe', async ({ page }) => {
  test.setTimeout(180000)
  await login(page)
  const results = []
  for (const width of [1440, 1280, 768, 390]) {
    await page.setViewportSize({ width, height: 900 })
    for (const [name, path] of [
      ['sources', '/management/sources' + suffix],
      ['detail', '/management/sources/operations' + suffix],
      ['editor', '/management/sources/operations/edit' + suffix],
      ['tables', '/management/sources/operations' + suffix + '&tab=tables'],
      ['organizations', '/management/organizations'],
      ['password', '/management/account/password'],
    ]) {
      await page.goto(path)
      await page.getByRole('heading', { level: 1 }).waitFor()
      if (name === 'tables')
        await page
          .getByRole('button', { name: '刷新数据库目录', exact: true })
          .waitFor()
      if (name === 'sources')
        await expect(page.getByText('已加载 50 条')).toBeVisible()
      await page.screenshot({
        path: resolve(output, name + '-' + width + '.png'),
        fullPage: true,
      })
      const audit = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
        .analyze()
      const serious = audit.violations.filter(
        (v) => v.impact === 'serious' || v.impact === 'critical',
      )
      results.push({
        width,
        name,
        violations: serious.map((v) => ({
          id: v.id,
          nodes: v.nodes.map((n) => n.target),
        })),
      })
      expect(serious, name + '@' + width).toEqual([])
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
        ),
        name + '@' + width + '无页面溢出',
      ).toBe(true)
      await page.keyboard.press('Tab')
      expect(
        await page.evaluate(() => document.activeElement?.tagName !== 'BODY'),
      ).toBe(true)
    }
  }
  writeFileSync(resolve(output, 'axe.json'), JSON.stringify(results, null, 2))
})

test('登录、字段抽屉和发布弹窗的键盘焦点与axe', async ({ page }) => {
  test.setTimeout(90000)
  const audits = []
  async function audit(name: string) {
    const result = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
      .analyze()
    const serious = result.violations.filter(
      (v) => v.impact === 'serious' || v.impact === 'critical',
    )
    audits.push({
      name,
      width: page.viewportSize()!.width,
      violations: serious,
    })
    expect(serious, name).toEqual([])
  }
  await page.goto('/management/login')
  await page.getByRole('heading', { name: '欢迎登录' }).waitFor()
  for (const width of [1440, 1280, 768, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await audit('login')
    await page.screenshot({
      path: resolve(output, 'login-' + width + '.png'),
      fullPage: true,
    })
  }
  await login(page)
  await page.goto('/management/sources/operations' + suffix + '&tab=tables')
  const table = page.getByRole('button', {
    name: 'warehouse.orders',
    exact: true,
  })
  await table.click()
  await expect(page.getByRole('dialog')).toContainText('DECIMAL(18,2)')
  await audit('column-drawer')
  await page.screenshot({
    path: resolve(output, 'columns-390.png'),
    fullPage: true,
  })
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toBeHidden()
  await expect(table).toBeFocused()
  const publish = page.getByRole('button', { name: '发布', exact: true })
  await publish.click()
  await expect(page.getByText('当前草稿已发布，无需重复发布。')).toBeVisible()
  await audit('release-modal')
  await page.screenshot({
    path: resolve(output, 'release-390.png'),
    fullPage: true,
  })
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toBeHidden()
  await expect(publish).toBeFocused()
  writeFileSync(
    resolve(output, 'axe-dialogs.json'),
    JSON.stringify(audits, null, 2),
  )
})
