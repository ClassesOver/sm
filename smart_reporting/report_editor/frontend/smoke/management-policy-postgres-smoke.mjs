import assert from 'node:assert/strict'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

let input = ''
for await (const chunk of process.stdin) input += chunk
const config = JSON.parse(input)
await mkdir(config.output, { recursive: true })
const origin = 'http://127.0.0.1:5194'
const html = (await readFile(new URL('../management.html', import.meta.url), 'utf8')).replace('src="/src/', 'src="/management/src/')
const server = await createServer({ configFile: 'vite.management.config.ts', server: { host: '127.0.0.1', port: 5194, strictPort: true } })
await server.listen()
const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 390, height: 1100 } })
  page.setDefaultTimeout(15000)
  await page.context().addCookies([{ name: 'report_management_session', value: config.token, url: origin + '/management/' }])
  let posts = 0, recoveryReads = 0, defaultWrites = 0, retirement, retiredDefaultObserved = false
  const http = [], errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/management/statistical-policies?**', route => route.fulfill({ contentType: 'text/html', body: html }))
  await page.route('**/management/api/v1/**', async route => {
    const req = route.request(), url = new URL(req.url())
    const response = await route.fetch({ url: config.apiOrigin + url.pathname + url.search,
      headers: { ...req.headers(), cookie: 'report_management_session=' + config.token } })
    const body = await response.json()
    if (req.method() === 'GET' && url.pathname.includes('/report-policy-defaults/') && retirement
      && body.policyVersion?.revision === 1 && body.issues?.some(item => item.code === 'semantic_asset_retired' && item.impact === 'unavailable')) retiredDefaultObserved = true
    http.push({ path: url.pathname, query: url.search, method: req.method(), status: response.status(),
      body: url.pathname.endsWith('/me') ? { username: body.username } : body })
    if (req.method() === 'POST' && url.pathname.endsWith('/retire')) {
      assert.equal(response.status(), 200, JSON.stringify(body)); posts++; retirement = body
      assert.deepEqual(body.replacement, { policyId: 'monthly-budget', revision: 2 })
      return route.abort('failed')
    }
    if (req.method() === 'PUT' && url.pathname.includes('/report-policy-defaults/')) {
      assert.equal(retiredDefaultObserved, true)
      assert.equal(response.status(), 200, JSON.stringify(body)); defaultWrites++
      assert.deepEqual(body.policyVersion, { policyId: 'monthly-budget', revision: 2 })
      return route.abort('failed')
    }
    if (retirement && url.pathname.endsWith('/monthly-budget')) recoveryReads++
    await route.fulfill({ response })
  })
  await page.goto(origin + '/management/statistical-policies?' + new URLSearchParams({ database: config.database, companyId: config.companyId }))
  await page.getByRole('button', { name: '版本与影响', exact: true }).click()
  const selectRevision = async revision => {
    await page.getByRole('combobox', { name: '查看发布版本', exact: true }).click()
    await page.locator('.ant-select-item-option-content:visible').getByText('版本 ' + revision, { exact: true }).click()
  }
  await selectRevision(1)
  const section = page.getByRole('region', { name: '口径版本退役', exact: true })
  await section.getByText('场景默认 · budget_execution · 版本 1').waitFor()
  await section.getByRole('checkbox', { name: '登记替代版本', exact: true }).check()
  await section.getByRole('button', { name: '选择合成预算执行修正版', exact: true }).click()
  await section.getByRole('combobox', { name: '替代发布版本', exact: true }).click()
  await page.locator('.ant-select-item-option-content:visible').getByText('版本 2', { exact: true }).click()
  await section.getByText('替代版本：合成预算执行修正版 · 版本 2', { exact: true }).waitFor()
  await section.getByRole('textbox', { name: '退役原因', exact: true }).fill('合成验收：此版规则停止用于新报告，保留精确历史定义。')
  await section.getByRole('checkbox', { name: '确认退役影响', exact: true }).check()
  await section.screenshot({ path: config.output + '/form-390.png', animations: 'disabled' })
  await section.getByRole('button', { name: '确认退役此版本', exact: true }).click()
  await section.getByText('退役结果待确认', { exact: false }).waitFor()
  await page.reload(); await page.getByRole('button', { name: '版本与影响', exact: true }).click(); await selectRevision(1)
  await section.getByRole('button', { name: '读取原退役结果', exact: true }).click()
  await section.getByText('已确认原退役登记', { exact: false }).waitFor()
  await section.screenshot({ path: config.output + '/retirement-result-390.png', animations: 'disabled' })
  await selectRevision(2)
  const defaults = page.getByRole('region', { name: '场景默认口径', exact: true })
  await defaults.getByText('当前默认：monthly-budget · 版本 1 · 配置版本 1', { exact: true }).waitFor()
  await defaults.getByRole('checkbox', { name: '确认调整场景默认', exact: true }).check()
  await defaults.screenshot({ path: config.output + '/default-form-390.png', animations: 'disabled' })
  await defaults.getByRole('button', { name: '确认调整默认', exact: true }).click()
  await defaults.getByText('默认调整结果待确认', { exact: false }).waitFor()
  await page.reload(); await page.getByRole('button', { name: '版本与影响', exact: true }).click()
  await defaults.getByRole('button', { name: '读取原默认调整结果', exact: true }).click()
  await defaults.getByText('当前默认与原目标一致', { exact: false }).waitFor()
  await page.addScriptTag({ path: fileURLToPath(new URL('../node_modules/axe-core/axe.min.js', import.meta.url)) })
  const axe = await page.evaluate(async () => (await window.axe.run('main')).violations.filter(item => ['serious', 'critical'].includes(item.impact)).map(item => item.id))
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
  await defaults.screenshot({ path: config.output + '/result-390.png', animations: 'disabled' })
  assert.equal(posts, 1); assert.equal(defaultWrites, 1); assert.ok(recoveryReads >= 1); assert.deepEqual(axe, []); assert.equal(overflow, false); assert.deepEqual(errors, [])
  await writeFile(config.output + '/http-evidence.json', JSON.stringify(http, null, 2))
  await writeFile(config.output + '/browser-evidence.json', JSON.stringify({ posts, recoveryReads, defaultWrites, retiredDefaultObserved, axe, overflow, errors, retirement }, null, 2))
} finally { await browser.close(); await server.close() }
