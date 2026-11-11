import assert from 'node:assert/strict'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { mkdir, readFile, writeFile } from 'node:fs/promises'

let input = ''
for await (const chunk of process.stdin) input += chunk
const config = JSON.parse(input), origin = 'http://127.0.0.1:5212'
await mkdir(config.output, { recursive: true })
const html = (await readFile(new URL('../management.html', import.meta.url), 'utf8')).replace('src="/src/', 'src="/management/src/')
const server = await createServer({ configFile: 'vite.management.config.ts', server: { host: '127.0.0.1', port: 5212, strictPort: true } })
await server.listen()
const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  page.setDefaultTimeout(20000)
  await page.context().addCookies([{ name: 'report_management_session', value: config.token, url: origin + '/management/' }])
  const http = [], errors = []
  let metricSaves = 0, metricPublications = 0, policySaves = 0, policyPublications = 0, decisionPosts = 0, decisionUnknownReadbacks = 0, linkedVersions = []
  page.on('pageerror', error => errors.push(error.message))
  for (const name of ['metrics', 'statistical-policies', 'report-issues']) await page.route('**/management/' + name + '?**', route => route.fulfill({ contentType: 'text/html', body: html }))
  await page.route('**/management/api/v1/**', async route => {
    const request = route.request(), url = new URL(request.url())
    const response = await route.fetch({ url: config.apiOrigin + url.pathname + url.search,
      headers: { ...request.headers(), origin: 'https://reports.test', cookie: 'report_management_session=' + config.token } })
    const body = await response.json()
    http.push({ path: url.pathname, method: request.method(), status: response.status(), body: url.pathname.endsWith('/me') ? { username: body.username } : body })
    if (request.method() !== 'GET') {
      assert.equal(response.status(), 200, JSON.stringify(body))
      if (url.pathname.endsWith('/metrics/rate/draft')) metricSaves++
      if (url.pathname.endsWith('/metrics/rate/publish')) metricPublications++
      if (url.pathname.endsWith('/statistical-policies/monthly-budget/draft')) policySaves++
      if (url.pathname.endsWith('/statistical-policies/monthly-budget/publish')) policyPublications++
    }
    if (config.decisions && request.method() === 'POST' && url.pathname.endsWith('/decision')) {
      decisionPosts++; linkedVersions = body.review.correctedVersions
      return route.abort('failed')
    }
    await route.fulfill({ response })
  })
  const query = { database: config.database, companyId: config.companyId }
  const decide = async (link) => {
    await page.goto(origin + '/management/report-issues?' + new URLSearchParams(query))
    await page.getByRole('button', { name: '查看并裁定', exact: true }).click()
    const form = page.locator('#issue-decision')
    await form.getByRole('radio', { name: '采纳，登记候选改动', exact: true }).check()
    await form.getByLabel('裁定理由', { exact: true }).fill(link ? '已正式发布精确修复版本，等待新报告和回归。' : '采纳原始行反例，待正式修复和独立回归。')
    await form.getByLabel('候选改动', { exact: true }).fill('总体执行率改用实际合计除以预算合计')
    await form.getByLabel('原始反例与预期结果', { exact: true }).fill('A预算100实际60+30，B预算200实际100；平均90%和50%是70%，总体190/300是63.33%。')
    if (link) {
      await form.getByRole('checkbox', { name: '选择预算执行率（合计比率），修订2', exact: true }).check()
      await form.getByRole('radio', { name: '统计口径', exact: true }).check()
      await form.getByRole('checkbox', { name: '选择C02合计执行率，修订3', exact: true }).check()
    }
    await page.screenshot({ path: config.output + (link ? '/linked-before-1440.png' : '/accepted-before-1440.png'), fullPage: true })
    await form.getByRole('button', { name: '确认登记裁定', exact: true }).click()
    await page.getByText('裁定结果待确认', { exact: false }).waitFor()
    await page.reload()
    await page.getByRole('button', { name: '读取原裁定结果', exact: true }).click()
    await page.getByText('已确认原裁定生效；采纳仍为待修复。', { exact: true }).waitFor()
    decisionUnknownReadbacks++
    await page.screenshot({ path: config.output + (link ? '/linked-readback-1440.png' : '/accepted-readback-1440.png'), fullPage: true })
  }
  if (config.decisions) await decide(false)
  await page.goto(origin + '/management/metrics?' + new URLSearchParams({ ...query, editMetric: 'rate' }))
  await page.locator('#metric-name').fill('预算执行率（合计比率）')
  for (const [label, name, id] of [['分子', '实际额', 'actual'], ['分母', '预算额', 'budget']]) {
    const picker = page.getByRole('region', { name: label + '依赖指标', exact: true })
    await picker.getByRole('button', { name: '选择' + label + '指标', exact: true }).click()
    await picker.getByRole('button', { name: '选择' + name + ' · ' + id, exact: true }).click()
    await picker.getByRole('combobox', { name: label + '发布版本', exact: true }).click()
    await page.locator('.ant-select-item-option-content:visible').getByText('版本 1', { exact: true }).click()
    await picker.getByText('名称：' + name, { exact: false }).waitFor()
  }
  await page.locator('#metric-dimension-field-0').fill('warehouse.test.budget.project_id')
  await page.getByRole('button', { name: '保存指标草稿', exact: true }).click()
  await page.getByText('草稿已保存，正式口径和报告尚未改变。', { exact: true }).waitFor()
  await page.getByRole('checkbox', { name: '确认指标发布', exact: true }).check()
  await page.getByRole('button', { name: '发布指标版本', exact: true }).click()
  await page.getByText('指标版本已发布；不会自动替换口径或默认。', { exact: false }).waitFor()
  await page.screenshot({ path: config.output + '/metric-published-1440.png', fullPage: true })
  await page.goto(origin + '/management/statistical-policies?' + new URLSearchParams({ ...query, editPolicy: 'monthly-budget' }))
  await page.locator('#policy-name').fill('C02合计执行率')
  const picker = page.getByRole('region', { name: '指标 1依赖指标', exact: true })
  await picker.getByRole('button', { name: '选择指标 1指标', exact: true }).click()
  await picker.getByRole('button', { name: '选择预算执行率（合计比率） · rate', exact: true }).click()
  await picker.getByRole('combobox', { name: '指标 1发布版本', exact: true }).click()
  await page.locator('.ant-select-item-option-content:visible').getByText('版本 2', { exact: true }).click()
  await picker.getByText('名称：预算执行率（合计比率）', { exact: false }).waitFor()
  await page.getByRole('button', { name: '保存口径草稿', exact: true }).click()
  await page.getByText('口径草稿已保存；发布和设为默认需分别明确确认。', { exact: true }).waitFor()
  await page.getByRole('button', { name: '核对发布变更', exact: true }).click()
  await page.getByRole('region', { name: '口径发布逐项差异', exact: true }).waitFor()
  await page.screenshot({ path: config.output + '/policy-before-publish-1440.png', fullPage: true })
  await page.getByRole('checkbox', { name: '确认口径发布', exact: true }).check()
  await page.getByRole('button', { name: '发布口径版本', exact: true }).click()
  await page.getByText('口径版本已发布，默认未改变。', { exact: false }).waitFor()
  if (config.decisions) await decide(true)
  await page.waitForLoadState('networkidle')
  assert.equal(metricSaves, 1); assert.equal(metricPublications, 1)
  assert.equal(policySaves, 1); assert.equal(policyPublications, 1); assert.deepEqual(errors, [])
  await writeFile(config.output + '/http-evidence.json', JSON.stringify(http, null, 2))
  await writeFile(config.output + '/browser-evidence.json', JSON.stringify({
    metricSaves, metricPublications, policySaves, policyPublications, errors, decisionPosts, decisionUnknownReadbacks, linkedVersions, issueId: config.issueId,
    metricVersion: { metricId: 'rate', revision: 2 }, policyVersion: { policyId: 'monthly-budget', revision: 3 },
    scope: '完整管理页真实HTTP/隔离PG明确编辑精确依赖、保存和发布；不设默认，不自动修改旧报告',
  }, null, 2))
} finally {
  for (const context of browser.contexts()) for (const page of context.pages()) await page.unrouteAll({ behavior: 'wait' })
  await browser.close(); await server.close()
}
