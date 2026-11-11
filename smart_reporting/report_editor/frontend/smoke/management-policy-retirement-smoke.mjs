import { chromium } from 'playwright'
import { createServer } from 'vite'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const directory = fileURLToPath(new URL('../../../../docs/superpowers/reports/artifacts/2026-11-11-policy-replacement-ui/browser', import.meta.url))
await mkdir(directory, { recursive: true })
const html = (await readFile(new URL('../management.html', import.meta.url), 'utf8')).replace('src="/src/', 'src="/management/src/')
const server = await createServer({ configFile: 'vite.management.config.ts', server: { host: '127.0.0.1', port: 5194, strictPort: true } })
await server.listen()
const browser = await chromium.launch({ headless: true })
const results = []
try {
  for (const width of [1440, 1280, 768, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 1100 } })
    page.setDefaultTimeout(15000)
    let retirement = null, posts = 0, readsAfterLoss = 0
    const calls = [], errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.route('**/management/statistical-policies?**', route => route.fulfill({ contentType: 'text/html', body: html }))
    await page.route('**/management/api/v1/**', async route => {
      const req = route.request(), url = new URL(req.url())
      calls.push({ path: url.pathname, method: req.method(), query: url.search })
      if (url.pathname.endsWith('/me')) return route.fulfill({ json: { username: 'admin', csrfToken: 'synthetic-csrf' } })
      if (url.pathname.endsWith('/scopes')) return route.fulfill({ json: { items: [
        { id: 'org100', name: '第一机构', database: 'warehouse', companyId: '100' },
        { id: 'org200', name: '第二机构', database: 'warehouse', companyId: '200' }], nextCursor: null } })
      if (url.pathname.includes('/report-policy-defaults/')) return route.fulfill({ json: { version: 1,
        policyVersion: { policyId: 'monthly', revision: 1 }, backgroundReleaseId: null, issues: [] } })
      if (url.pathname.endsWith('/statistical-policies')) return route.fulfill({ json: {
        items: url.searchParams.get('companyId') === '100' ? [{ policyId: 'monthly', name: '预算执行口径', draftVersion: 1, publishedRevision: 1 },
          { policyId: 'corrected', name: '预算执行修正版', draftVersion: 2, publishedRevision: 2 }] : [], nextCursor: null } })
      if (url.searchParams.has('companyId') && url.searchParams.get('companyId') !== '100') throw Error('foreign detail request')
      if (req.method() === 'POST') {
        posts++
        const body = req.postDataJSON()
        if (posts !== 1 || !url.pathname.endsWith('/monthly/versions/1/retire') || body.companyId !== '100'
          || body.scopeDatabase !== 'warehouse' || !body.reason || body.replacement?.policyId !== 'corrected'
          || body.replacement?.revision !== 2) throw Error('wrong retirement request')
        retirement = { assetType: 'statistical_policy', assetId: 'monthly', revision: 1, reason: body.reason, replacement: body.replacement }
        return route.abort('failed')
      }
      if (url.pathname.endsWith('/impact')) return route.fulfill({ json: url.searchParams.has('after')
        ? { items: [{ kind: 'report', referenceId: '旧月报', policyRevision: 1, basisId: 'basis-original' }], nextCursor: null }
        : { items: [{ kind: 'default', referenceId: '月度预算分析', policyRevision: 1, basisId: null }], nextCursor: 'default:monthly' } })
      if (url.pathname.endsWith('/monthly')) {
        if (url.searchParams.get('revision') !== '1') throw Error('wrong exact version')
        if (retirement) readsAfterLoss++
        return route.fulfill({ json: { draft: null, published: { revision: 1, document: { name: '预算执行口径', scenario: 'budget_execution' }, contentHash: 'synthetic-hash-1' }, retirement } })
      }
      if (url.pathname.endsWith('/corrected')) return route.fulfill({ json: { published: { revision: 2, document: { name: '预算执行修正版', scenario: 'budget_execution' }, contentHash: 'synthetic-hash-2' }, retirement: null } })
      throw Error('unexpected HTTP: ' + url.pathname)
    })
    await page.goto('http://127.0.0.1:5194/management/statistical-policies?database=warehouse&companyId=100')
    await page.getByRole('button', { name: '版本与影响', exact: true }).first().click()
    const section = page.getByRole('region', { name: '口径版本退役', exact: true })
    await section.getByText('场景默认 · 月度预算分析 · 版本 1').waitFor()
    await section.getByRole('checkbox', { name: '登记替代版本', exact: true }).check()
    await section.getByRole('button', { name: '选择预算执行修正版', exact: true }).click()
    await section.getByRole('combobox', { name: '替代发布版本', exact: true }).click()
    await page.locator('.ant-select-item-option-content:visible').getByText('版本 2', { exact: true }).click()
    await section.getByText('替代版本：预算执行修正版 · 版本 2', { exact: true }).waitFor()
    await section.getByRole('textbox', { name: '退役原因', exact: true }).fill('已核对原始反例，此版本停止用于新报告，保留原报告。')
    await section.getByRole('checkbox', { name: '确认退役影响', exact: true }).check()
    if (await section.getByRole('button', { name: '确认退役此版本', exact: true }).isEnabled()) throw Error('incomplete impact allowed POST')
    await section.getByRole('button', { name: '加载更多影响', exact: true }).click()
    await section.getByText('历史报告 · 旧月报 · 版本 1').waitFor()
    await section.screenshot({ path: `${directory}/retirement-form-${width}.png`, animations: 'disabled' })
    await section.getByRole('button', { name: '确认退役此版本', exact: true }).focus(); await page.keyboard.press('Enter')
    await section.getByText('退役结果待确认', { exact: false }).waitFor()
    await page.reload(); await page.getByRole('button', { name: '版本与影响', exact: true }).first().click()
    await section.getByRole('button', { name: '读取原退役结果', exact: true }).waitFor()
    if (!await section.getByRole('button', { name: '读取原退役结果', exact: true }).evaluate(node => node === document.activeElement)) throw Error('missing recovery focus')
    await page.keyboard.press('Enter')
    await section.getByText('已确认原退役登记', { exact: false }).waitFor()
    await page.addScriptTag({ path: fileURLToPath(new URL('../node_modules/axe-core/axe.min.js', import.meta.url)) })
    const axe = await page.evaluate(async () => (await window.axe.run('main')).violations.filter(item => ['serious', 'critical'].includes(item.impact)).map(item => item.id))
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
    await section.screenshot({ path: `${directory}/retirement-result-${width}.png`, animations: 'disabled' })
    await page.getByRole('combobox', { name: '当前组织', exact: true }).click(); await page.getByText('第二机构', { exact: true }).click()
    await page.waitForURL(url => url.searchParams.get('companyId') === '200')
    await page.locator('.ant-empty-description').waitFor()
    if (await section.count()) throw Error('foreign retirement still visible')
    const result = { width, posts, readsAfterLoss, axe, overflow, errors, calls }
    results.push(result)
    if (posts !== 1 || readsAfterLoss < 1 || axe.length || overflow || errors.length) throw Error(JSON.stringify(result))
    await page.close()
  }
  await writeFile(`${directory}/browser-evidence.json`, JSON.stringify({ scope: '实际ManagementApp、受控HTTP；不是真实PostgreSQL退役或业务签认', results }, null, 2))
  console.log(JSON.stringify(results.map(({ calls, ...item }) => item)))
} finally { await browser.close(); await server.close() }
