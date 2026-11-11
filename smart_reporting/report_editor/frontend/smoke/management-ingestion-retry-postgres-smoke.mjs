import assert from 'node:assert/strict'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
let input = ''
for await (const chunk of process.stdin) input += chunk
const config = JSON.parse(input), origin = 'http://127.0.0.1:5203'
await mkdir(config.output, { recursive: true })
const html = (await readFile(new URL('../management.html', import.meta.url), 'utf8')).replace('src="/src/', 'src="/management/src/')
const server = await createServer({ configFile: 'vite.management.config.ts', server: { host: '127.0.0.1', port: 5203, strictPort: true } })
await server.listen()
const browser = await chromium.launch({ headless: true })
try {
 const page = await browser.newPage({ viewport: { width: 390, height: 1100 } })
 page.setDefaultTimeout(15000)
 await page.context().addCookies([{ name: 'report_management_session', value: config.token, url: origin + '/management/' }])
 const http = [], errors = [], widths = []
 let retries = 0
 page.on('pageerror', error => errors.push(error.message))
 await page.route('**/management/knowledge?**', route => route.fulfill({ contentType: 'text/html', body: html }))
 await page.route('**/management/api/v1/**', async route => {
  const req = route.request(), url = new URL(req.url())
  const result = await route.fetch({ url: config.apiOrigin + url.pathname + url.search, headers: { ...req.headers(), cookie: 'report_management_session=' + config.token } })
  const body = await result.json()
  http.push({ path: url.pathname, query: url.search, method: req.method(), status: result.status(), body: url.pathname.endsWith('/me') ? { username: body.username } : body })
  if (req.method() === 'POST') {
   assert.equal(result.status(), 200, JSON.stringify(body)); assert.ok(url.pathname.endsWith('/'+config.jobId+'/retry'))
   retries++; assert.equal(req.postDataJSON().expectedAttempt, 1); assert.equal(req.postDataJSON().companyId, 'a')
   return route.abort('failed')
  }
  await route.fulfill({ response: result })
 })
 await page.goto(origin + '/management/knowledge?' + new URLSearchParams({ database: config.database, companyId: config.companyId, document: 'budget-rules', revision: '1' }))
 await page.getByRole('button', { name: '查看此修订解析任务', exact: true }).click()
 await page.getByRole('button', { name: '查看任务 ' + config.jobId, exact: true }).click()
 assert.equal(new URL(page.url()).searchParams.get('job'), config.jobId)
 await page.getByRole('region', { name: '解析失败重试', exact: true }).waitFor()
 assert.equal(retries, 0)
 assert.equal(await page.getByRole('button', { name: '重新排队解析', exact: true }).isDisabled(), true)
 await page.addScriptTag({ path: fileURLToPath(new URL('../node_modules/axe-core/axe.min.js', import.meta.url)) })
 for (const width of [1440, 1280, 768, 390]) {
  await page.setViewportSize({ width, height: 1100 })
  await page.evaluate(async () => { await new Promise(requestAnimationFrame); await Promise.all(document.getAnimations().filter(a => a.effect?.getComputedTiming().iterations !== Infinity).map(a => a.finished.catch(() => undefined))) })
  const axe = await page.evaluate(async () => (await window.axe.run('main')).violations.filter(i => ['serious', 'critical'].includes(i.impact)).map(i => i.id))
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
  assert.deepEqual(axe, []); assert.equal(overflow, false)
  await page.screenshot({ path: config.output + '/retry-before-' + width + '.png', fullPage: true, animations: 'disabled' })
  widths.push({ width, axe, overflow })
 }
 await page.getByRole('checkbox', { name: '确认重新解析', exact: true }).check()
 await page.getByRole('button', { name: '重新排队解析', exact: true }).click()
 await page.getByText('重试结果待确认：', { exact: false }).waitFor()
 await page.reload()
 const recover = page.getByRole('button', { name: '读取原重试状态', exact: true })
 await recover.waitFor(); await recover.focus(); await page.keyboard.press('Enter')
 await page.getByText('当前任务已推进', { exact: false }).waitFor()
 await page.getByRole('button', { name: '读取解析状态', exact: true }).click()
 await page.getByText('已解析，待发布 · 修订 1 · 已尝试 2 次', { exact: true }).waitFor()
 await page.screenshot({ path: config.output + '/retry-recovered-390.png', fullPage: true, animations: 'disabled' })
 assert.equal(retries, 1); assert.deepEqual(errors, [])
 await writeFile(config.output + '/http-evidence.json', JSON.stringify(http, null, 2))
 await writeFile(config.output + '/browser-evidence.json', JSON.stringify({ retries, errors, widths, unknownResponseReadback: true, taskDiscoveredFromRevision: true }, null, 2))
} finally { await browser.close(); await server.close() }
