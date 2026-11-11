import assert from 'node:assert/strict'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
let input = ''
for await (const chunk of process.stdin) input += chunk
const config = JSON.parse(input), origin = 'http://127.0.0.1:5204'
await mkdir(config.output, { recursive: true })
const html = (await readFile(new URL('../management.html', import.meta.url), 'utf8')).replace('src="/src/', 'src="/management/src/')
const server = await createServer({ configFile: 'vite.management.config.ts', server: { host: '127.0.0.1', port: 5204, strictPort: true } })
await server.listen()
const browser = await chromium.launch({ headless: true })
try {
 const page = await browser.newPage({ viewport: { width: 390, height: 1100 } })
 page.setDefaultTimeout(15000)
 await page.context().addCookies([{ name: 'report_management_session', value: config.token, url: origin + '/management/' }])
 const http = [], errors = [], widths = [], requestIds = []
 let publications = 0
 page.on('pageerror', error => errors.push(error.message))
 await page.route('**/management/knowledge?**', route => route.fulfill({ contentType: 'text/html', body: html }))
 await page.route('**/management/api/v1/**', async route => {
  const req = route.request(), url = new URL(req.url())
  const result = await route.fetch({ url: config.apiOrigin + url.pathname + url.search, headers: { ...req.headers(), cookie: 'report_management_session=' + config.token } })
  const body = await result.json()
  http.push({ path: url.pathname, query: url.search, method: req.method(), status: result.status(), body: url.pathname.endsWith('/me') ? { username: body.username } : body })
  if (req.method() === 'POST') {
   assert.equal(result.status(), 201, JSON.stringify(body)); assert.ok(url.pathname.endsWith('/business-evidence-releases'))
   publications++; requestIds.push(req.postDataJSON().requestId); assert.equal(req.postDataJSON().companyId, 'a')
   return route.abort('failed')
  }
  await route.fulfill({ response: result })
 })
 await page.goto(origin + '/management/knowledge?' + new URLSearchParams({ database: config.database, companyId: config.companyId }))
 const manager = page.getByRole('region', { name: '证据集合发布', exact: true })
 await manager.getByRole('button', { name: '选择集合原件', exact: true }).click()
 await manager.getByRole('button', { name: '读取修订 budget-rules', exact: true }).click()
 assert.equal(await manager.getByRole('button', { name: '加入 budget-rules 修订 2', exact: true }).isDisabled(), true)
 await manager.getByRole('button', { name: '加入 budget-rules 修订 1', exact: true }).click()
 const source = manager.getByRole('button', { name: '预览集合原件 budget-rules 修订 1', exact: true })
 await source.focus(); await page.keyboard.press('Enter')
 await page.getByRole('dialog').getByText('执行额合计÷预算额合计，不能平均各组比率。', { exact: true }).waitFor()
 await page.keyboard.press('Escape'); await page.getByRole('dialog').waitFor({ state: 'detached' })
 await page.waitForFunction(() => document.activeElement?.textContent === '预览集合原件 budget-rules 修订 1')
 await page.addScriptTag({ path: fileURLToPath(new URL('../node_modules/axe-core/axe.min.js', import.meta.url)) })
 for (const width of [1440, 1280, 768, 390]) {
  await page.setViewportSize({ width, height: 1100 })
  await page.evaluate(async () => { await new Promise(requestAnimationFrame); await Promise.all(document.getAnimations().filter(a => a.effect?.getComputedTiming().iterations !== Infinity).map(a => a.finished.catch(() => undefined))) })
  const axe = await page.evaluate(async () => (await window.axe.run('main')).violations.filter(i => ['serious', 'critical'].includes(i.impact)).map(i => i.id))
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
  if (overflow) {
   await page.screenshot({ path: config.output + '/overflow-' + width + '.png', fullPage: true, animations: 'disabled' })
   const offenders = await page.evaluate(() => [...document.querySelectorAll('body *')].filter(e => { const r=e.getBoundingClientRect();return r.right>innerWidth+1 && r.width>0 }).map(e=>({tag:e.tagName,cls:e.className,width:e.getBoundingClientRect().width,text:e.textContent.slice(0,100)})).slice(0,18))
   await writeFile(config.output + '/overflow.json', JSON.stringify({width,offenders,geometry:await page.evaluate(()=>({inner:innerWidth,scroll:document.documentElement.scrollWidth,body:document.body.scrollWidth,client:document.documentElement.clientWidth,bodyStyle:document.body.getAttribute('style')}))},null,2))
  }
  assert.deepEqual(axe, []); assert.equal(overflow, false)
  await page.screenshot({ path: config.output + '/release-before-' + width + '.png', fullPage: true, animations: 'disabled' })
  widths.push({ width, axe, overflow })
 }
 await manager.getByRole('checkbox', { name: '确认发布证据集合', exact: true }).check()
 await manager.getByRole('button', { name: '发布证据集合', exact: true }).click()
 await manager.getByText('集合发布结果待确认：', { exact: false }).waitFor()
 await page.reload()
 await manager.getByRole('button', { name: '读取原集合发布结果', exact: true }).click()
 await manager.getByText('原请求集合已发布', { exact: false }).waitFor()
 await manager.getByRole('button', { name: '结束本次集合发布', exact: true }).click()
 const kind = manager.getByRole('combobox', { name: '集合用途', exact: true })
 await kind.click(); await page.locator('.ant-select-item-option:visible').filter({ hasText: '背景材料' }).click()
 await manager.getByRole('button', { name: '选择集合原件', exact: true }).click()
 await manager.getByRole('button', { name: '读取修订 budget-background', exact: true }).click()
 await manager.getByRole('button', { name: '加入 budget-background 修订 1', exact: true }).click()
 await manager.getByRole('checkbox', { name: '确认发布证据集合', exact: true }).check()
 await manager.getByRole('button', { name: '发布证据集合', exact: true }).click()
 await manager.getByText('集合发布结果待确认：', { exact: false }).waitFor()
 await page.reload()
 await manager.getByRole('button', { name: '读取原集合发布结果', exact: true }).click()
 await manager.getByText('原请求集合已发布', { exact: false }).waitFor()
 await manager.getByText('当前登记可供选择', { exact: true }).waitFor()
 assert.equal(publications, 2); assert.deepEqual(errors, [])
 await page.screenshot({ path: config.output + '/background-recovered-390.png', fullPage: true, animations: 'disabled' })
 await page.getByRole('combobox', { name: '当前组织', exact: true }).click()
 await Promise.all([page.waitForResponse(response => new URL(response.url()).pathname.endsWith('/business-evidence-releases/catalog') && new URL(response.url()).searchParams.get('companyId') === 'b'), page.getByText('组织B', { exact: true }).click()])
 await manager.getByText('当前用途暂无已发布集合。', { exact: true }).waitFor()
 assert.equal(await manager.getByRole('button', { name: '读取原集合发布结果', exact: true }).count(), 0)
 await page.waitForLoadState('networkidle')
 await writeFile(config.output + '/http-evidence.json', JSON.stringify(http, null, 2))
 await writeFile(config.output + '/browser-evidence.json', JSON.stringify({ publications, requestIds, errors, widths, scopeSwitchClearsPublication: true }, null, 2))
} finally { await browser.close(); await server.close() }
