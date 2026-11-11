import { test, expect, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
const credentials = JSON.parse(
  readFileSync(
    process.env.MANAGEMENT_E2E_CREDENTIALS ||
      '/tmp/management-depth-credentials.json',
    'utf8',
  ),
)
const output = resolve('../../../output/management-depth/screenshots')
mkdirSync(output, { recursive: true })
test.afterEach(async ({ page }, info) => {
  await page
    .locator('input[type=password]')
    .evaluateAll((inputs) =>
      inputs.forEach((input) => ((input as HTMLInputElement).value = '')),
    )
  await info.attach('error-context', {
    body: await page.locator('body').innerText(),
    contentType: 'text/plain',
  })
})
const suffix = '?database=warehouse&companyId=100'
async function login(page: Page) {
  await page.goto('/management/login')
  await page.getByLabel('密码', { exact: true }).fill(credentials.password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: '数据源', exact: true }),
  ).toBeVisible()
}
test('完整应用入口、登录、分页查找、保留凭据、并发恢复与发布', async ({
  page,
}) => {
  const exceptions: string[] = []
  page.on('pageerror', (error) => exceptions.push(error.message))
  await page.goto('/management/')
  await expect(page).toHaveURL(/management\/login/)
  await login(page)
  await page.getByRole('combobox', { name: '当前组织' }).click()
  await page.getByText('华东运营', { exact: true }).click()
  await expect(page.getByText('已加载 50 条')).toBeVisible()
  await page.getByRole('button', { name: '加载更多', exact: true }).click()
  await expect(page.getByText('已加载 55 条')).toBeVisible()
  await page
    .locator('a[href*="/management/sources/operations?"]')
    .first()
    .click()
  await expect(page.getByRole('button', { name: '编辑草稿' })).toBeVisible()
  await page.getByRole('button', { name: '编辑草稿' }).click()
  await expect(page.getByText('保持现有连接', { exact: true })).toBeVisible()
  await expect(page.getByLabel('连接地址（含账号密码）')).toHaveCount(0)
  await page
    .getByLabel('数据源名称', { exact: true })
    .fill('经营数仓·真实浏览器验收')
  // 另一个客户端在同一有效会话下修改草稿，真实服务器返回409。
  const me = await (await page.request.get('/management/api/v1/me')).json()
  const detail = await (
    await page.request.get(
      '/management/api/v1/sources/operations?scopeDatabase=warehouse&companyId=100',
    )
  ).json()
  const concurrent = await page.request.put(
    '/management/api/v1/sources/operations/draft',
    {
      headers: {
        origin: 'http://127.0.0.1:7789',
        'x-csrf-token': me.csrfToken,
      },
      data: {
        scopeDatabase: 'warehouse',
        companyId: '100',
        expectedVersion: detail.draft.version,
        name: '并发客户端名称-' + detail.draft.version,
        database: 'warehouse',
        reportingProfileVersionId: 'base:1',
        metadataVersionId: 'operations:1',
      },
    },
  )
  expect(concurrent.status()).toBe(200)
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect(
    page.getByRole('dialog', { name: '草稿已被其他操作更新', exact: true }),
  ).toBeVisible()
  await page
    .getByLabel('我的输入：经营数仓·真实浏览器验收', { exact: true })
    .check()
  await page.getByRole('button', { name: '采用合并结果继续编辑' }).click()
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect(page.getByRole('status')).toContainText(
    '草稿已保存 v' + (detail.draft.version + 2),
  )
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await page.getByRole('button', { name: '发布', exact: true }).click()
  await expect(
    page.getByRole('dialog', { name: '确认发布数据源' }),
  ).toBeVisible()
  await page.getByRole('button', { name: '确认发布', exact: true }).click()
  await expect(page.getByText('已发布 v1', { exact: true })).toBeVisible()
  const current = await (
    await page.request.get(
      '/management/api/v1/sources/operations?scopeDatabase=warehouse&companyId=100',
    )
  ).json()
  expect(current.published.revision).toBe(1)
  expect(current.hasUnpublishedChanges).toBe(false)
  await page.screenshot({
    path: resolve(output, 'detail-1440.png'),
    fullPage: true,
  })
  expect(exceptions).toEqual([])
})
test('键盘登录、不同视口、组织隔离和可访问性', async ({ page }) => {
  await page.goto('/management/login')
  await page.getByLabel('密码', { exact: true }).focus()
  await page.keyboard.type(credentials.password)
  await page.keyboard.press('Enter')
  await expect(
    page.getByRole('heading', { name: '数据源', exact: true }),
  ).toBeVisible()
  const results = []
  for (const width of [390, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/management/sources' + suffix)
    await expect(page.getByText('已加载 50 条')).toBeVisible()
    const audit = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
      .analyze()
    results.push({
      width,
      violations: audit.violations.map((v) => ({
        id: v.id,
        impact: v.impact,
        nodes: v.nodes.map((n) => n.target),
      })),
    })
    await page.screenshot({
      path: resolve(output, `sources-${width}.png`),
      fullPage: true,
    })
    expect(
      audit.violations
        .filter((v) => v.impact === 'serious' || v.impact === 'critical')
        .map((v) => ({ id: v.id, targets: v.nodes.map((n) => n.target) })),
    ).toEqual([])
  }
  writeFileSync(resolve(output, 'axe.json'), JSON.stringify(results, null, 2))
  await page.goto(
    '/management/sources/operations?database=warehouse&companyId=200',
  )
  await expect(
    page.getByRole('heading', { name: '其他机构同标识数仓' }),
  ).toBeVisible()
  await page.goto('/management/sources?database=warehouse&companyId=300')
  await expect(page.getByText('当前组织暂无数据源')).toBeVisible()
})
test('故障注入：刷新失败保留旧数据，写请求中断不自动重试', async ({ page }) => {
  await login(page)
  await page.goto('/management/sources' + suffix)
  await expect(page.getByText('已加载 50 条')).toBeVisible()
  await page.route('**/management/api/v1/sources?**', (route) => route.abort())
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await expect(page.getByText(/刷新失败，当前显示上次读取的数据/)).toBeVisible()
  await expect(
    page.getByRole('link', { name: '经营数仓·真实浏览器验收', exact: true }),
  ).toBeVisible()
  await page.unroute('**/management/api/v1/sources?**')
  await page.goto('/management/sources/operations/edit' + suffix)
  await page.getByLabel('数据源名称', { exact: true }).fill('不应静默重试')
  let attempts = 0
  await page.route('**/management/api/v1/sources/operations/draft', (route) => {
    attempts++
    return route.abort()
  })
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect(page.getByText('提交结果待确认，已暂停重复提交')).toBeVisible()
  await expect(
    page.getByRole('button', { name: '保存草稿', exact: true }),
  ).toBeDisabled()
  expect(attempts).toBe(1)
  await page.getByRole('button', { name: '读取最新状态', exact: true }).click()
  await page
    .getByRole('button', { name: '采用服务器版本', exact: true })
    .click()
  await expect(page.getByLabel('数据源名称', { exact: true })).toHaveValue(
    '经营数仓·真实浏览器验收',
  )
})
test('未保存导航可取消，改密撤销会话并退出', async ({ page }) => {
  await login(page)
  await page.goto('/management/sources/operations/edit' + suffix)
  await page.getByLabel('数据源名称', { exact: true }).fill('保留未保存输入')
  await page.getByRole('link', { name: '组织', exact: true }).click()
  await expect(
    page.getByRole('dialog', { name: '放弃未保存的修改？' }),
  ).toBeVisible()
  await page.getByRole('button', { name: '继续编辑' }).click()
  await expect(page.getByLabel('数据源名称', { exact: true })).toHaveValue(
    '保留未保存输入',
  )
  await page.getByRole('link', { name: '组织', exact: true }).click()
  await page.getByRole('button', { name: '放弃修改', exact: true }).click()
  await page.goto('/management/account/password')
  await page.getByLabel('当前密码', { exact: true }).fill(credentials.password)
  const updated = credentials.password + '-updated'
  await page.getByLabel('新密码', { exact: true }).fill(updated)
  await page.getByRole('button', { name: '更新密码', exact: true }).click()
  await expect(page.getByRole('heading', { name: '欢迎登录' })).toBeVisible()
  expect((await page.request.get('/management/api/v1/me')).status()).toBe(401)
  await page.getByLabel('密码', { exact: true }).fill(updated)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: '修改密码', exact: true }),
  ).toBeVisible()
  // 恢复临时账户密码，便于独立重复执行单个用例。
  await page.goto('/management/account/password')
  await page.getByLabel('当前密码', { exact: true }).fill(updated)
  await page.getByLabel('新密码', { exact: true }).fill(credentials.password)
  await page.getByRole('button', { name: '更新密码', exact: true }).click()
  await expect(page.getByRole('heading', { name: '欢迎登录' })).toBeVisible()
  await login(page)
  await page.getByRole('button', { name: 'admin' }).click()
  await page.getByRole('menuitem', { name: '退出登录' }).click()
  await expect(page.getByRole('heading', { name: '欢迎登录' })).toBeVisible()
  expect((await page.request.get('/management/api/v1/me')).status()).toBe(401)
})

test('登录、已发布详情、编辑和发布弹层无严重无障碍问题', async ({ page }) => {
  const audits = []
  async function audit(state: string) {
    const result = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
      .analyze()
    const issues = result.violations.map((v) => ({
      id: v.id,
      impact: v.impact,
      targets: v.nodes.map((n) => n.target),
    }))
    audits.push({ state, issues })
    expect(
      issues.filter((v) => v.impact === 'serious' || v.impact === 'critical'),
    ).toEqual([])
  }
  await page.goto('/management/login')
  await page.getByRole('heading', { name: '欢迎登录' }).waitFor()
  await audit('login')
  await page.screenshot({ path: resolve(output, 'login-1440.png') })
  await login(page)
  await page.goto('/management/sources/operations' + suffix)
  await page.getByRole('heading', { name: '经营数仓·真实浏览器验收' }).waitFor()
  await audit('published-detail')
  const trigger = page.getByRole('button', { name: '发布', exact: true })
  await trigger.click()
  await page.getByText('当前草稿已发布，无需重复发布。').waitFor()
  await audit('release')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(trigger).toBeFocused()
  await page.getByRole('button', { name: '编辑草稿' }).click()
  await page.getByLabel('数据源名称', { exact: true }).waitFor()
  await audit('editor')
  writeFileSync(
    resolve(output, 'axe-key-states.json'),
    JSON.stringify(audits, null, 2),
  )
})

test('保存回执与刷新失败分开，创建后清除连接输入', async ({ page }) => {
  await login(page)
  await page.goto('/management/sources/operations/edit' + suffix)
  await page.getByLabel('数据源名称', { exact: true }).waitFor()
  const before = await (
    await page.request.get(
      '/management/api/v1/sources/operations?scopeDatabase=warehouse&companyId=100',
    )
  ).json()
  await page.route('**/management/api/v1/sources/operations?**', (route) =>
    route.abort(),
  )
  let writes = 0
  page.on('request', (request) => {
    if (request.method() === 'PUT') writes++
  })
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect(page.getByRole('status')).toContainText(
    '草稿已保存 v' + (before.draft.version + 1),
  )
  await expect(page.getByRole('alert')).toContainText(
    '草稿已保存，关联数据刷新失败',
  )
  expect(writes).toBe(1)
  await page.unroute('**/management/api/v1/sources/operations?**')
  const after = await (
    await page.request.get(
      '/management/api/v1/sources/operations?scopeDatabase=warehouse&companyId=100',
    )
  ).json()
  expect(after.draft.version).toBe(before.draft.version + 1)
  await page.goto('/management/sources/new' + suffix)
  await page.getByLabel('数据源标识', { exact: true }).fill('new')
  const longName = '浏览器新建长中文名称用于验证窄屏显示与连接凭据保存后的清理'
  await page.getByLabel('数据源名称', { exact: true }).fill(longName)
  await page.getByLabel('连接数据库', { exact: true }).fill('warehouse')
  await page
    .getByLabel('连接地址（含账号密码）', { exact: true })
    .fill('starrocks://reader:isolated-browser-secret@localhost:9030/warehouse')
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect(page).toHaveURL(/sources\/new\/view/)
  await expect(page.getByRole('heading', { name: longName })).toBeVisible()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  for (const width of [390, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true)
  }
})

test('新建响应丢失读回后转为编辑，未创建时可保留输入重试', async ({ page }) => {
  await login(page)
  async function fill(id: string) {
    await page.goto('/management/sources/new' + suffix)
    await page.getByLabel('数据源标识', { exact: true }).fill(id)
    await page.getByLabel('数据源名称', { exact: true }).fill('恢复新建')
    await page.getByLabel('连接数据库', { exact: true }).fill('warehouse')
    await page
      .getByLabel('连接地址（含账号密码）', { exact: true })
      .fill(
        'starrocks://reader:isolated-recovery-secret@localhost:9030/warehouse',
      )
  }
  await fill('never-submitted')
  await page.route('**/management/api/v1/sources', (route) => route.abort())
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await page.getByText('提交结果待确认，已暂停重复提交').waitFor()
  await page.getByRole('button', { name: '读取最新状态', exact: true }).click()
  await expect(
    page.getByRole('button', { name: '保存草稿', exact: true }),
  ).toBeEnabled()
  await expect(page.getByLabel('数据源名称', { exact: true })).toHaveValue(
    '恢复新建',
  )
  await expect(
    page.getByLabel('连接地址（含账号密码）', { exact: true }),
  ).toHaveValue('')
  await page.unroute('**/management/api/v1/sources')
  // 明确放弃这个尚未创建的草稿，再验证服务端已提交而响应丢失的分支。
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await page.getByRole('button', { name: '放弃修改', exact: true }).click()
  await fill('response-lost')
  let posts = 0
  await page.route('**/management/api/v1/sources', async (route) => {
    posts++
    const response = await route.fetch()
    expect(response.status()).toBe(201)
    await route.abort()
  })
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await page.getByText('提交结果待确认，已暂停重复提交').waitFor()
  await page.getByRole('button', { name: '读取最新状态', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '核对提交结果' })).toBeVisible()
  await page
    .getByRole('button', { name: '保留我的输入继续编辑', exact: true })
    .click()
  expect(posts).toBe(1)
  await page.unroute('**/management/api/v1/sources')
  await expect(
    page.getByRole('heading', { name: '编辑数据源草稿' }),
  ).toBeVisible()
  await page.getByLabel('数据源名称', { exact: true }).fill('恢复后继续编辑')
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect(page).toHaveURL(/sources\/response-lost\/edit/)
  const result = await (
    await page.request.get(
      '/management/api/v1/sources/response-lost?scopeDatabase=warehouse&companyId=100',
    )
  ).json()
  expect(result.draft.version).toBe(2)
  expect(result.draft.name).toBe('恢复后继续编辑')
})
