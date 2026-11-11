import assert from 'node:assert/strict'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

let input = ''
for await (const chunk of process.stdin) input += chunk
const config = JSON.parse(input)
await mkdir(config.output, { recursive: true })
const origin = 'http://127.0.0.1:5198'
const html = (await readFile(new URL('../management.html', import.meta.url), 'utf8')).replace('src="/src/', 'src="/management/src/')
const server = await createServer({ configFile: 'vite.management.config.ts', server: { host: '127.0.0.1', port: 5198, strictPort: true } })
await server.listen()
const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 390, height: 1100 } })
  page.setDefaultTimeout(15000)
  await page.context().addCookies([{ name: 'report_management_session', value: config.token, url: origin + '/management/' }])
  const http = [], errors = [], widths = []
  let saves = 0, publications = 0
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/management/metrics?**', route => route.fulfill({ contentType: 'text/html', body: html }))
  await page.route('**/management/api/v1/**', async route => {
    const req = route.request(), url = new URL(req.url())
    const response = await route.fetch({ url: config.apiOrigin + url.pathname + url.search,
      headers: { ...req.headers(), cookie: 'report_management_session=' + config.token } })
    const body = await response.json()
    http.push({ path: url.pathname, query: url.search, method: req.method(), status: response.status(),
      body: url.pathname.endsWith('/me') ? { username: body.username } : body })
    if (req.method() === 'PUT' || req.method() === 'POST') {
      assert.equal(response.status(), 200, JSON.stringify(body))
      assert.equal(req.postDataJSON().companyId, 'a')
      const metricId = url.pathname.split('/').at(-2)
      assert.ok(['budget', 'rate'].includes(metricId))
      if (req.method() === 'PUT') {
        assert.ok(url.pathname.endsWith('/draft')); saves++
        assert.equal(req.postDataJSON().expectedVersion, metricId === 'budget' ? 1 : 0)
        assert.equal(req.postDataJSON().definition.scopeId, undefined)
        assert.equal(req.postDataJSON().definition.revision, undefined)
      } else {
        assert.ok(url.pathname.endsWith('/publish')); publications++
        assert.equal(req.postDataJSON().expectedVersion, metricId === 'budget' ? 2 : 1)
      }
      return route.abort('failed')
    }
    await route.fulfill({ response })
  })
  await page.goto(origin + '/management/metrics?' + new URLSearchParams({ database: config.database, companyId: config.companyId, editMetric: 'budget' }))
  await page.locator('#metric-name').fill('修订预算额')
  await page.locator('#metric-unit').fill('元')
  await page.getByRole('button', { name: '保存指标草稿', exact: true }).click()
  await page.getByText('提交结果待确认', { exact: false }).waitFor()
  await page.reload()
  const recover = page.getByRole('button', { name: '读取原提交结果', exact: true })
  await recover.waitFor()
  await recover.focus(); await page.keyboard.press('Enter')
  await page.getByText('当前草稿与原提交一致', { exact: false }).waitFor()
  const comparison = page.getByRole('region', { name: '指标发布变更', exact: true })
  assert.match(await comparison.innerText(), /当前发布：版本 1/)
  assert.match(await comparison.innerText(), /目标发布：版本 2/)
  assert.match(await comparison.innerText(), /原预算额/)
  assert.match(await comparison.innerText(), /修订预算额/)
  assert.match(await comparison.innerText(), /CNY/)
  await page.addScriptTag({ path: fileURLToPath(new URL('../node_modules/axe-core/axe.min.js', import.meta.url)) })
  for (const width of [1440, 1280, 768, 390]) {
    await page.setViewportSize({ width, height: 1100 })
    const axe = await page.evaluate(async () => (await window.axe.run('main')).violations.filter(i => ['serious', 'critical'].includes(i.impact)).map(i => i.id))
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
    assert.deepEqual(axe, []); assert.equal(overflow, false)
    await page.screenshot({ path: config.output + '/publish-comparison-' + width + '.png', fullPage: true, animations: 'disabled' })
    widths.push({ width, axe, overflow })
  }
  const scroll = page.getByRole('region', { name: '指标发布字段对比，可滚动', exact: true })
  await scroll.focus(); await page.keyboard.press('ArrowRight')
  await page.getByRole('checkbox', { name: '确认指标发布', exact: true }).check()
  await page.getByRole('button', { name: '发布指标版本', exact: true }).click()
  await page.getByText('提交结果待确认', { exact: false }).waitFor()
  await page.reload(); await recover.click()
  await page.getByText('当前发布与原提交一致', { exact: false }).waitFor()
  await page.getByRole('textbox', { name: '新指标标识', exact: true }).fill('rate')
  await page.getByRole('button', { name: '创建指标', exact: true }).click()
  await page.getByText('编辑指标 · rate', { exact: true }).waitFor()
  await page.locator('#metric-name').fill('预算执行率')
  await page.locator('#metric-unit').fill('%')
  await page.getByRole('combobox', { name: '指标计算方法', exact: true }).click()
  await page.locator('.ant-select-item-option-content:visible').getByText('比率（精确分子÷分母）', { exact: true }).click()
  for (const [label, id, name, revision] of [['分子', 'actual', '实际额', 1], ['分母', 'budget', '修订预算额', 2]]) {
    const picker = page.getByRole('region', { name: label + '依赖指标', exact: true })
    await picker.getByRole('button', { name: '选择' + label + '指标', exact: true }).click()
    await picker.getByRole('button', { name: '选择' + name + ' · ' + id, exact: true }).click()
    assert.match(await picker.innerText(), /请明确选择发布版本/)
    await picker.getByRole('combobox', { name: label + '发布版本', exact: true }).click()
    await page.locator('.ant-select-item-option-content:visible').getByText('版本 ' + revision, { exact: true }).click()
    await picker.getByText('名称：' + name, { exact: false }).waitFor()
  }
  await page.getByRole('button', { name: '添加维度', exact: true }).click()
  await page.locator('#metric-dimension-0').fill('project')
  await page.locator('#metric-dimension-field-0').fill('warehouse.test.budget.project_id')
  await page.getByRole('checkbox', { name: '作为计算粒度', exact: true }).check()
  await page.getByRole('button', { name: '保存指标草稿', exact: true }).click()
  await page.getByText('提交结果待确认', { exact: false }).waitFor()
  await page.reload(); await recover.click()
  await page.getByText('当前草稿与原提交一致', { exact: false }).waitFor()
  await page.getByRole('checkbox', { name: '确认指标发布', exact: true }).check()
  await page.getByRole('button', { name: '发布指标版本', exact: true }).click()
  await page.getByText('提交结果待确认', { exact: false }).waitFor()
  await page.reload(); await recover.click()
  await page.getByText('当前发布与原提交一致', { exact: false }).waitFor()
  await page.addScriptTag({ path: fileURLToPath(new URL('../node_modules/axe-core/axe.min.js', import.meta.url)) })
  const ratioAxe = await page.evaluate(async () => (await window.axe.run('main')).violations.filter(i => ['serious', 'critical'].includes(i.impact)).map(i => i.id))
  assert.deepEqual(ratioAxe, [])
  await page.screenshot({ path: config.output + '/ratio-published-390.png', fullPage: true, animations: 'disabled' })
  assert.equal(saves, 2); assert.equal(publications, 2); assert.deepEqual(errors, [])
  await page.getByRole('combobox', { name: '当前组织', exact: true }).click()
  await Promise.all([
    page.waitForResponse(response => new URL(response.url()).pathname.endsWith('/metrics') && new URL(response.url()).searchParams.get('companyId') === 'b'),
    page.getByText('组织B', { exact: true }).click(),
  ])
  await page.getByRole('region', { name: '指标定义编辑', exact: true }).waitFor({ state: 'detached' })
  await page.waitForLoadState('networkidle')
  await writeFile(config.output + '/http-evidence.json', JSON.stringify(http, null, 2))
  await writeFile(config.output + '/browser-evidence.json', JSON.stringify({ saves, publications, errors, widths,
    ratioAxe, keyboardComparisonFocused: true, scopeSwitchClearsEditor: true }, null, 2))
} finally { await browser.close(); await server.close() }
