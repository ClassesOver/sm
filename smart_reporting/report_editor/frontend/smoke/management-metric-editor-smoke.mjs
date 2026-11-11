import assert from 'node:assert/strict'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
const directory = fileURLToPath(new URL('../../../../docs/superpowers/reports/artifacts/2026-11-11-metric-editor-ui/browser', import.meta.url))
await mkdir(directory, { recursive: true })
const html = (await readFile(new URL('../management.html', import.meta.url), 'utf8')).replace('src="/src/', 'src="/management/src/')
const server = await createServer({ configFile: 'vite.management.config.ts', server: { host: '127.0.0.1', port: 5197, strictPort: true } })
await server.listen()
const browser = await chromium.launch({ headless: true }), results = []
try {
 for (const width of [1440, 1280, 768, 390]) {
  const page = await browser.newPage({ viewport: { width, height: 1100 } })
  page.setDefaultTimeout(15000)
  let draft = null, published = null, saves = 0, publications = 0
  const errors = [], calls = []
  page.on('pageerror', e => errors.push(e.message))
  await page.route('**/management/metrics?**', route => route.fulfill({ contentType: 'text/html', body: html }))
  await page.route('**/management/api/v1/**', async route => {
   const req = route.request(), url = new URL(req.url())
   calls.push({ path: url.pathname, method: req.method(), query: url.search })
   if (url.pathname.endsWith('/me')) return route.fulfill({ json: { username: 'admin', csrfToken: 'synthetic-csrf' } })
   if (url.pathname.endsWith('/scopes')) return route.fulfill({ json: { items: [
    { id: 'a', name: '组织A', database: 'warehouse', companyId: 'a' }, { id: 'b', name: '组织B', database: 'warehouse', companyId: 'b' }], nextCursor: null } })
   if (url.pathname.endsWith('/metrics')) return route.fulfill({ json: { items: draft ? [{ metricId: 'budget', name: draft.document.name, draftVersion: draft.version, publishedRevision: published?.revision ?? null }] : [], nextCursor: null } })
   if (req.method() === 'PUT') {
    const body = req.postDataJSON(); assert.equal(body.expectedVersion, 0); assert.equal(body.companyId, 'a')
    assert.equal(body.definition.scopeId, undefined); assert.equal(body.definition.revision, undefined)
    saves++; draft = { version: 1, contentHash: 'synthetic-hash', document: { ...body.definition, scopeId: 'a', revision: 1 } }
    return route.abort('failed')
   }
   if (req.method() === 'POST') {
    assert.equal(req.postDataJSON().expectedVersion, 1); publications++
    published = { revision: 1, contentHash: draft.contentHash, document: draft.document }
    return route.abort('failed')
   }
   if (url.pathname.endsWith('/budget')) return draft ? route.fulfill({ json: { draft, published, retirement: null } })
    : route.fulfill({ status: 404, json: { code: 'management_metric_not_found' } })
   throw Error('unexpected ' + url.pathname)
  })
  await page.goto('http://127.0.0.1:5197/management/metrics?database=warehouse&companyId=a')
  await page.getByRole('textbox', { name: '新指标标识', exact: true }).fill('budget')
  await page.getByRole('button', { name: '创建指标', exact: true }).click()
  await page.locator('#metric-name').fill('预算额')
  await page.locator('#metric-unit').fill('元')
  await page.locator('#metric-field').fill('source.db.budget.amount')
  await page.locator('#metric-time').fill('source.db.budget.day')
  await page.getByRole('button', { name: '添加维度', exact: true }).click()
  await page.locator('#metric-dimension-0').fill('project')
  await page.locator('#metric-dimension-field-0').fill('source.db.budget.project')
  await page.getByRole('checkbox', { name: '作为计算粒度', exact: true }).check()
  await page.screenshot({ path: directory + '/editor-' + width + '.png', fullPage: true, animations: 'disabled' })
  await page.getByRole('button', { name: '保存指标草稿', exact: true }).click()
  await page.getByText('提交结果待确认', { exact: false }).waitFor()
  await page.reload(); await page.getByRole('button', { name: '读取原提交结果', exact: true }).click()
  await page.getByText('当前草稿与原提交一致', { exact: false }).waitFor()
  await page.getByRole('checkbox', { name: '确认指标发布', exact: true }).check()
  await page.getByRole('button', { name: '发布指标版本', exact: true }).click()
  await page.getByText('提交结果待确认', { exact: false }).waitFor()
  await page.reload(); await page.getByRole('button', { name: '读取原提交结果', exact: true }).click()
  await page.getByText('当前发布与原提交一致', { exact: false }).waitFor()
  await page.addScriptTag({ path: fileURLToPath(new URL('../node_modules/axe-core/axe.min.js', import.meta.url)) })
  const axe = await page.evaluate(async () => (await window.axe.run('main')).violations.filter(i => ['serious', 'critical'].includes(i.impact)).map(i => i.id))
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
  assert.deepEqual(axe, []); assert.equal(overflow, false); assert.deepEqual(errors, []); assert.equal(saves, 1); assert.equal(publications, 1)
  assert.deepEqual(draft.document.grain, ['project'])
  await page.screenshot({ path: directory + '/recovered-' + width + '.png', fullPage: true, animations: 'disabled' })
  results.push({ width, saves, publications, axe, overflow, errors, calls, draft, published })
  await page.close()
 }
 await writeFile(directory + '/evidence.json', JSON.stringify(results, null, 2))
 console.log('四尺寸创建、草稿保存和发布未知响应恢复通过。')
} finally { await browser.close(); await server.close() }
