import assert from 'node:assert/strict'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
let input = ''
for await (const chunk of process.stdin) input += chunk
const config = JSON.parse(input), origin = 'http://127.0.0.1:5201'
await mkdir(config.output, { recursive: true })
const html = (await readFile(new URL('../management.html', import.meta.url), 'utf8')).replace('src="/src/', 'src="/management/src/')
const server = await createServer({ configFile: 'vite.management.config.ts', server: { host: '127.0.0.1', port: 5201, strictPort: true } })
await server.listen()
const browser = await chromium.launch({ headless: true })
try {
 const page = await browser.newPage({ viewport: { width: 390, height: 1100 } })
 page.setDefaultTimeout(15000)
 await page.context().addCookies([{ name: 'report_management_session', value: config.token, url: origin + '/management/' }])
 const http = [], errors = [], widths = [], previewWidths = []
 let reviews = 0, originalDownloaded = false
 page.on('pageerror', error => errors.push(error.message))
 await page.route('**/management/knowledge?**', route => route.fulfill({ contentType: 'text/html', body: html }))
 await page.route('**/management/api/v1/**', async route => {
  const req = route.request(), url = new URL(req.url())
  const result = await route.fetch({ url: config.apiOrigin + url.pathname + url.search, headers: { ...req.headers(), cookie: 'report_management_session=' + config.token } })
  if (url.pathname.endsWith('/original')) {
   assert.equal(result.status(), 200)
   assert.match((await result.body()).toString(), /项目B需单独核对全年期间/)
   originalDownloaded = true
   http.push({ path: url.pathname, query: url.search, method: req.method(), status: result.status(), sizeBytes: (await result.body()).length })
   return route.fulfill({ response: result })
  }
  const body = await result.json()
  http.push({ path: url.pathname, query: url.search, method: req.method(), status: result.status(), body: url.pathname.endsWith('/me') ? { username: body.username } : body })
  if (req.method() === 'POST') {
   assert.equal(result.status(), 200, JSON.stringify(body)); assert.ok(url.pathname.endsWith('/revisions/2/review'))
   reviews++; assert.equal(req.postDataJSON().companyId, 'a'); assert.equal(req.postDataJSON().decision, 'approved')
   return route.abort('failed')
  }
  await route.fulfill({ response: result })
 })
 await page.goto(origin + '/management/knowledge?' + new URLSearchParams({ database: config.database, companyId: config.companyId, document: 'budget-rules', revision: '2' }))
 const detail = page.getByRole('region', { name: '原件修订详情', exact: true })
 await detail.getByText('修订预算管理制度 · 修订 2', { exact: true }).waitFor()
 await page.addScriptTag({ path: fileURLToPath(new URL('../node_modules/axe-core/axe.min.js', import.meta.url)) })
 for (const width of [1440, 1280, 768, 390]) {
  await page.setViewportSize({ width, height: 1100 })
  const axe = await page.evaluate(async () => (await window.axe.run('main')).violations.filter(i => ['serious', 'critical'].includes(i.impact)).map(i => i.id))
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
  assert.deepEqual(axe, []); assert.equal(overflow, false)
  await page.screenshot({ path: config.output + '/knowledge-review-' + width + '.png', fullPage: true, animations: 'disabled' })
  widths.push({ width, axe, overflow })
 }
 const source = detail.getByRole('button', { name: '预览待核对原文', exact: true })
 await source.focus(); await page.keyboard.press('Enter')
 const drawer = page.getByRole('dialog')
 await drawer.getByText('项目B需单独核对全年期间。', { exact: true }).waitFor()
 await drawer.getByText('管理审核预览：尚未作为已发布制度依据', { exact: false }).waitFor()
 for (const width of [1440, 1280, 768, 390]) {
  await page.setViewportSize({ width, height: 1100 })
  const axe = await page.evaluate(async () => (await window.axe.run('[role=dialog]')).violations.filter(i => ['serious', 'critical'].includes(i.impact)).map(i => i.id))
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
  assert.deepEqual(axe, []); assert.equal(overflow, false)
  await page.screenshot({ path: config.output + '/pending-preview-' + width + '.png', fullPage: true, animations: 'disabled' })
  previewWidths.push({ width, axe, overflow })
 }
 await page.keyboard.press('Escape'); await drawer.waitFor({ state: 'detached' })
 await page.waitForFunction(() => document.activeElement?.textContent === '预览待核对原文')
 await Promise.all([page.waitForEvent('download'), detail.getByRole('link', { name: '下载此修订原件', exact: true }).click()])
 await detail.getByRole('textbox', { name: '审核理由', exact: true }).fill('已核对原件合计比值及项目B全年期间。')
 await detail.getByRole('checkbox', { name: '确认原件审核', exact: true }).check()
 await detail.getByRole('button', { name: '提交原件审核', exact: true }).click()
 await page.getByText('原件审核结果待确认，请读取原审核结果', { exact: false }).waitFor()
 await page.reload()
 const recover = page.getByRole('button', { name: '读取原审核结果', exact: true })
 await recover.waitFor(); await recover.focus(); await page.keyboard.press('Enter')
 await page.getByText('当前状态与原审核决定一致', { exact: false }).waitFor()
 assert.equal(reviews, 1); assert.deepEqual(errors, []); assert.equal(originalDownloaded, true)
 await page.screenshot({ path: config.output + '/review-recovered-390.png', fullPage: true, animations: 'disabled' })
 await page.getByRole('combobox', { name: '当前组织', exact: true }).click()
 await Promise.all([page.waitForResponse(response => new URL(response.url()).pathname.endsWith('/business-documents') && new URL(response.url()).searchParams.get('companyId') === 'b'), page.getByText('组织B', { exact: true }).click()])
 await page.getByText('组织B同名原件', { exact: true }).waitFor()
 await detail.waitFor({ state: 'detached' }); await page.waitForLoadState('networkidle')
 await writeFile(config.output + '/http-evidence.json', JSON.stringify(http, null, 2))
 await writeFile(config.output + '/browser-evidence.json', JSON.stringify({ reviews, originalDownloaded, errors, widths, previewWidths, sourceKeyboardEscapeAndFocus: true, scopeSwitchClearsDetail: true }, null, 2))
} finally { await browser.close(); await server.close() }
