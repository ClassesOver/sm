import assert from 'node:assert/strict'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

let input = ''
for await (const chunk of process.stdin) input += chunk
const config = JSON.parse(input)
await mkdir(config.output, { recursive: true })
const origin = 'http://127.0.0.1:5196'
const html = (await readFile(new URL('../management.html', import.meta.url), 'utf8')).replace('src="/src/', 'src="/management/src/')
const server = await createServer({ configFile: 'vite.management.config.ts', server: { host: '127.0.0.1', port: 5196, strictPort: true } })
await server.listen()
const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 390, height: 1100 } })
  page.setDefaultTimeout(15000)
  await page.context().addCookies([{ name: 'report_management_session', value: config.token, url: origin + '/management/' }])
  const http = [], errors = []
  let writes = 0
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/management/metrics?**', route => route.fulfill({ contentType: 'text/html', body: html }))
  await page.route('**/management/api/v1/**', async route => {
    const req = route.request(), url = new URL(req.url())
    const response = await route.fetch({ url: config.apiOrigin + url.pathname + url.search,
      headers: { ...req.headers(), cookie: 'report_management_session=' + config.token } })
    const body = await response.json()
    http.push({ path: url.pathname, query: url.search, method: req.method(), status: response.status(),
      body: url.pathname.endsWith('/me') ? { username: body.username } : body })
    if (req.method() === 'POST') {
      assert.ok(url.pathname.endsWith('/budget/versions/1/retire'))
      assert.equal(response.status(), 200, JSON.stringify(body)); writes++
      assert.deepEqual(body.replacement, { metricId: 'budget', revision: 2 })
      return route.abort('failed')
    }
    await route.fulfill({ response })
  })
  await page.goto(origin + '/management/metrics?' + new URLSearchParams({ database: config.database, companyId: config.companyId, metricId: 'budget', revision: '1' }))
  const section = page.getByRole('region', { name: '指标版本与影响', exact: true })
  await section.getByText('old-run', { exact: true }).waitFor()
  const retirement = page.getByRole('region', { name: '指标版本退役', exact: true })
  await retirement.getByRole('checkbox', { name: '登记替代指标版本', exact: true }).check()
  await retirement.getByRole('button', { name: '选择预算额 · budget', exact: true }).click()
  await retirement.getByRole('combobox', { name: '替代指标发布版本', exact: true }).click()
  await page.locator('.ant-select-item-option-content:visible').getByText('版本 2', { exact: true }).click()
  await retirement.getByRole('textbox', { name: '指标退役原因', exact: true }).fill('合成退役')
  await retirement.getByRole('checkbox', { name: '确认指标退役影响', exact: true }).check()
  await retirement.screenshot({ path: config.output + '/replacement-form-390.png', animations: 'disabled' })
  await retirement.getByRole('button', { name: '确认退役指标版本', exact: true }).click()
  await retirement.getByText('指标退役结果待确认', { exact: false }).waitFor()
  await page.reload()
  await retirement.getByRole('button', { name: '读取原指标退役结果', exact: true }).click()
  await retirement.getByText('已确认原指标退役登记', { exact: false }).waitFor()
  assert.equal(await section.getByText('new-run', { exact: true }).count(), 0)
  await section.screenshot({ path: config.output + '/version-1-390.png', animations: 'disabled' })
  await page.reload(); await section.getByText('old-run', { exact: true }).waitFor()
  assert.equal(new URL(page.url()).searchParams.get('revision'), '1')
  await page.getByRole('combobox', { name: '查看发布版本', exact: true }).click()
  await page.locator('.ant-select-item-option-content:visible').getByText('版本 2', { exact: true }).click()
  await section.getByText('new-run', { exact: true }).waitFor()
  assert.equal(await section.getByText('old-run', { exact: true }).count(), 0)
  await page.goBack(); await section.getByText('old-run', { exact: true }).waitFor()
  await section.getByRole('region', { name: '指标影响明细，可滚动', exact: true }).focus()
  await page.keyboard.press('ArrowRight')
  await page.waitForFunction(() => document.querySelector('[aria-label="指标影响明细，可滚动"]').scrollLeft > 0)
  await page.addScriptTag({ path: fileURLToPath(new URL('../node_modules/axe-core/axe.min.js', import.meta.url)) })
  const axe = await page.evaluate(async () => (await window.axe.run('main')).violations.filter(item => ['serious', 'critical'].includes(item.impact)).map(item => item.id))
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
  assert.deepEqual(axe, []); assert.deepEqual(errors, []); assert.equal(overflow, false)
  const widths = []
  for (const width of [1440, 1280, 768, 390]) {
    await page.setViewportSize({ width, height: 1100 })
    const violations = await page.evaluate(async () => (await window.axe.run('main')).violations.filter(item => ['serious', 'critical'].includes(item.impact)).map(item => item.id))
    const wide = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
    assert.deepEqual(violations, []); assert.equal(wide, false)
    await section.screenshot({ path: config.output + '/retired-version-' + width + '.png', animations: 'disabled' })
    widths.push({ width, axe: violations, overflow: wide })
  }
  await page.getByRole('combobox', { name: '当前组织', exact: true }).click()
  await Promise.all([
    page.waitForResponse(response => new URL(response.url()).pathname.endsWith('/metrics')
      && new URL(response.url()).searchParams.get('companyId') === 'b'),
    page.getByText('组织B', { exact: true }).click(),
  ])
  await page.waitForURL(url => url.searchParams.get('companyId') === 'b')
  await section.waitFor({ state: 'detached' })
  await page.waitForLoadState('networkidle')
  assert.equal(await section.count(), 0)
  await writeFile(config.output + '/http-evidence.json', JSON.stringify(http, null, 2))
  assert.equal(writes, 1)
  await writeFile(config.output + '/browser-evidence.json', JSON.stringify({ axe, overflow, errors, writeRequests: writes, historicalVersionPreserved: true,
    selectedVersion2Isolated: true, keyboardScroll: true, scopeSwitchClearsDetails: true, widths }, null, 2))
} finally { await browser.close(); await server.close() }
