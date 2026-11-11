import assert from 'node:assert/strict'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const directory = fileURLToPath(new URL('../../../../docs/superpowers/reports/artifacts/2026-11-11-policy-default-ui/browser', import.meta.url))
await mkdir(directory, { recursive: true })
const html = (await readFile(new URL('../management.html', import.meta.url), 'utf8')).replace('src="/src/', 'src="/management/src/')
const server = await createServer({ configFile: 'vite.management.config.ts', server: { host: '127.0.0.1', port: 5195, strictPort: true } })
await server.listen()
const browser = await chromium.launch({ headless: true })
const results = []
try {
  for (const width of [1440, 1280, 768, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 1100 } })
    page.setDefaultTimeout(15000)
    const background = 'background-' + 'a'.repeat(64)
    let current = { version: 1, policyVersion: { policyId: 'monthly', revision: 1 }, backgroundReleaseId: background, issues: [] }
    let writes = 0, readsAfterLoss = 0
    const errors = [], calls = []
    page.on('pageerror', error => errors.push(error.message))
    await page.route('**/management/statistical-policies?**', route => route.fulfill({ contentType: 'text/html', body: html }))
    await page.route('**/management/api/v1/**', async route => {
      const req = route.request(), url = new URL(req.url())
      calls.push({ path: url.pathname, method: req.method(), query: url.search })
      if (url.pathname.endsWith('/me')) return route.fulfill({ json: { username: 'admin', csrfToken: 'synthetic-csrf' } })
      if (url.pathname.endsWith('/scopes')) return route.fulfill({ json: { items: [
        { id: 'org100', name: '第一机构', database: 'warehouse', companyId: '100' },
        { id: 'org200', name: '第二机构', database: 'warehouse', companyId: '200' }], nextCursor: null } })
      if (url.pathname.endsWith('/statistical-policies')) return route.fulfill({ json: { items: url.searchParams.get('companyId') === '100'
        ? [{ policyId: 'monthly', name: '预算执行修正版', draftVersion: 2, publishedRevision: 2 }] : [], nextCursor: null } })
      if (url.pathname.includes('/report-policy-defaults/')) {
        if (req.method() === 'PUT') {
          writes++
          const body = req.postDataJSON()
          assert.equal(body.expectedVersion, 1); assert.equal(body.companyId, '100'); assert.equal(body.scopeDatabase, 'warehouse')
          assert.equal(body.backgroundReleaseId, background); assert.deepEqual(body.policyVersion, { policyId: 'monthly', revision: 2 })
          current = { ...current, version: 2, policyVersion: body.policyVersion }
          return route.abort('failed')
        }
        if (writes) readsAfterLoss++
        return route.fulfill({ json: current })
      }
      if (url.pathname.endsWith('/impact')) return route.fulfill({ json: { items: [], nextCursor: null } })
      if (url.pathname.endsWith('/monthly')) return route.fulfill({ json: { published: { revision: 2, contentHash: 'synthetic-target-2',
        document: { name: '预算执行修正版', scenario: 'budget_execution' } }, retirement: null } })
      throw Error('unexpected request: ' + url.pathname)
    })
    await page.goto('http://127.0.0.1:5195/management/statistical-policies?database=warehouse&companyId=100')
    await page.getByRole('button', { name: '版本与影响', exact: true }).click()
    const defaults = page.getByRole('region', { name: '场景默认口径', exact: true })
    await defaults.getByText('当前默认：monthly · 版本 1 · 配置版本 1', { exact: true }).waitFor()
    assert.equal(await defaults.getByRole('button', { name: '确认调整默认', exact: true }).isEnabled(), false)
    await defaults.getByRole('checkbox', { name: '确认调整场景默认', exact: true }).check()
    await defaults.screenshot({ path: `${directory}/default-form-${width}.png`, animations: 'disabled' })
    await defaults.getByRole('button', { name: '确认调整默认', exact: true }).focus(); await page.keyboard.press('Enter')
    await defaults.getByText('默认调整结果待确认', { exact: false }).waitFor()
    await page.reload(); await page.getByRole('button', { name: '版本与影响', exact: true }).click()
    await defaults.getByRole('button', { name: '读取原默认调整结果', exact: true }).waitFor()
    assert.equal(await defaults.getByRole('button', { name: '读取原默认调整结果', exact: true }).evaluate(node => node === document.activeElement), true)
    await page.keyboard.press('Enter')
    await defaults.getByText('当前默认与原目标一致', { exact: false }).waitFor()
    await page.addScriptTag({ path: fileURLToPath(new URL('../node_modules/axe-core/axe.min.js', import.meta.url)) })
    const axe = await page.evaluate(async () => (await window.axe.run('main')).violations.filter(item => ['serious', 'critical'].includes(item.impact)).map(item => item.id))
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
    await defaults.screenshot({ path: `${directory}/default-result-${width}.png`, animations: 'disabled' })
    await page.getByRole('combobox', { name: '当前组织', exact: true }).click(); await page.getByText('第二机构', { exact: true }).click()
    await page.waitForURL(url => url.searchParams.get('companyId') === '200')
    await page.locator('.ant-empty-description').waitFor()
    assert.equal(await defaults.count(), 0)
    const result = { width, writes, readsAfterLoss, axe, overflow, errors, calls }
    results.push(result)
    assert.equal(writes, 1); assert.ok(readsAfterLoss >= 1); assert.deepEqual(axe, []); assert.equal(overflow, false); assert.deepEqual(errors, [])
    await page.close()
  }
  await writeFile(`${directory}/browser-evidence.json`, JSON.stringify({ scope: '实际ManagementApp及受控HTTP，非真实PG', results }, null, 2))
  console.log(JSON.stringify(results.map(({ calls, ...item }) => item)))
} finally { await browser.close(); await server.close() }
