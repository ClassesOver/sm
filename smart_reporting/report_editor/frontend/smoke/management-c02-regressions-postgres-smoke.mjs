import assert from 'node:assert/strict'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { createServer } from 'vite'

let input = ''
for await (const chunk of process.stdin) input += chunk
const config = JSON.parse(input), origin = 'http://127.0.0.1:5213'
await mkdir(config.output, { recursive: true })
const html = (await readFile(new URL('../management.html', import.meta.url), 'utf8')).replace('src="/src/', 'src="/management/src/')
const server = await createServer({ configFile: 'vite.management.config.ts', server: { host: '127.0.0.1', port: 5213, strictPort: true } })
await server.listen()
const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } })
  page.setDefaultTimeout(20000)
  await page.context().addCookies([{ name: 'report_management_session', value: config.token, url: origin + '/management/' }])
  const http = [], errors = [], receipts = [], viewports = []
  let posts = 0, unknownReadbacks = 0
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/management/report-issues?**', route => route.fulfill({ contentType: 'text/html', body: html }))
  // 业务响应来自隔离服务；只在成功写入后丢弃响应，验证未知结果不会自动重发。
  await page.route('**/management/api/v1/**', async route => {
    const request = route.request(), url = new URL(request.url())
    const response = await route.fetch({ url: config.apiOrigin + url.pathname + url.search,
      headers: { ...request.headers(), origin: 'https://reports.test', cookie: 'report_management_session=' + config.token } })
    const body = await response.json()
    http.push({ path: url.pathname, query: url.search, method: request.method(), status: response.status(),
      body: url.pathname.endsWith('/me') ? { username: body.username } : body })
    if (request.method() === 'POST' && url.pathname.endsWith('/regressions')) {
      assert.equal(response.status(), 200, JSON.stringify(body))
      assert.equal(body.issueId, config.issueId)
      assert.equal(body.request.targetRunId, config.targetRunId)
      assert.equal(body.request.calculationReceiptId, config.calculationReceiptId)
      assert.equal(body.businessApproval, 'not_performed')
      posts++; receipts.push(body)
      return route.abort('failed')
    }
    await route.fulfill({ response })
  })
  await page.goto(origin + '/management/report-issues?' + new URLSearchParams({ database: config.database, companyId: config.companyId }))
  const openIssue = () => page.getByRole('button', { name: '查看并裁定', exact: true }).click()
  await openIssue()
  for (const [value, status] of [['70', 'failed'], ['63.33', 'passed']]) {
    await page.getByRole('button', { name: '新建回归核验', exact: true }).click()
    const candidate = page.locator('.issue-regressions .ant-card').filter({ hasText: config.calculationReceiptId })
      .filter({ has: page.getByRole('button', { name: '选择此计算', exact: true }) })
    await candidate.getByRole('button', { name: '选择此计算', exact: true }).click()
    const form = page.locator('#issue-regression')
    await form.getByLabel('反例标识', { exact: true }).fill('C02')
    await form.getByLabel('独立预期依据', { exact: true }).fill(value === '70'
      ? '负例：项目比率90%与50%的均值70%不得被当作总体合计比率。'
      : '独立原始预算100+200=300、实际60+30+100=190，合计比率保留两位为63.33%。')
    assert.equal(await form.locator('fieldset').count(), 1)
    await form.getByRole('radio', { name: '可计算', exact: true }).check()
    assert.equal(await form.getByLabel('独立预期值', { exact: true }).inputValue(), '')
    await form.getByLabel('独立预期值', { exact: true }).fill(value)
    await form.getByLabel('比较小数位（留空为精确比较）', { exact: true }).fill('2')
    await page.screenshot({ path: config.output + '/expectation-' + status + '-1440.png', fullPage: true })
    await form.getByRole('button', { name: '确认快照核验并登记', exact: true }).focus()
    await page.keyboard.press('Enter')
    await page.getByText('核验登记结果待确认', { exact: false }).waitFor()
    assert.equal(receipts.at(-1).status, status)
    const count = posts
    await page.reload(); await openIssue()
    const read = page.getByRole('button', { name: '读取原回归结果', exact: true })
    await read.waitFor()
    assert.equal(posts, count)
    await read.click()
    await page.getByText('已确认原回归核验登记；业务预期尚未签认，问题未关闭。', { exact: true }).waitFor()
    assert.equal(posts, count)
    unknownReadbacks++
    await page.getByText(status === 'passed' ? '快照核验符合预期' : '快照核验不符合预期', { exact: true }).first().waitFor()
  }
  for (const width of [1440, 1280, 768, 390]) {
    await page.setViewportSize({ width, height: 1100 })
    await page.waitForLoadState('networkidle')
    await page.addScriptTag({ path: fileURLToPath(new URL('../node_modules/axe-core/axe.min.js', import.meta.url)) })
    const result = await page.evaluate(async () => ({ overflow: document.documentElement.scrollWidth > innerWidth,
      seriousOrCritical: (await window.axe.run('main')).violations.filter(item => ['serious', 'critical'].includes(item.impact))
        .map(item => ({ id: item.id, nodes: item.nodes.map(node => ({ target: node.target, summary: node.failureSummary })) })) }))
    viewports.push({ width, ...result })
    await writeFile(config.output + '/viewport-evidence.json', JSON.stringify(viewports, null, 2))
    await page.screenshot({ path: config.output + '/regressions-' + width + '.png', fullPage: true })
    assert.equal(result.overflow, false); assert.deepEqual(result.seriousOrCritical, [])
  }
  assert.equal(posts, 2); assert.equal(unknownReadbacks, 2); assert.deepEqual(errors, [])
  await writeFile(config.output + '/http-evidence.json', JSON.stringify(http, null, 2))
  await writeFile(config.output + '/browser-evidence.json', JSON.stringify({ posts, unknownReadbacks, receipts, errors, viewports,
    scope: '完整管理页真实HTTP/隔离PG快照回归，独立预期70失败、63.33通过；不代表业务负责人签认。' }, null, 2))
} finally {
  for (const context of browser.contexts()) for (const page of context.pages()) await page.unrouteAll({ behavior: 'wait' })
  await browser.close(); await server.close()
}
