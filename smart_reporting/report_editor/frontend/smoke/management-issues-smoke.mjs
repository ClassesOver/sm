import { chromium } from 'playwright'
import { readFile, mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
const directory = fileURLToPath(new URL('../../../../docs/superpowers/reports/artifacts/2026-11-11-management-issue-reviews-ui', import.meta.url))
await mkdir(directory, { recursive: true })
const html = (await readFile(new URL('../management.html', import.meta.url), 'utf8')).replace('src="/src/', 'src="/management/src/')
const browser = await chromium.launch({ headless: true })
const results = []
try {
  for (const width of [1440, 1280, 768, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 1100 } })
    let posts = 0, committed = null
    const calls = []
    const issue = { basisId: 'basis-1', reportId: 'report-1', revision: 2, version: 1,
      review: { issueId: 'issue-rate', objectRefs: ['subject-rate'], category: 'calculation',
        description: '预算执行率应使用实际合计190除以预算合计300，请核对报告中的70%。', status: 'open', decisionReason: '' }, proposal: null }
    await page.route('**/management/report-issues?**', route => route.fulfill({ contentType: 'text/html', body: html }))
    await page.route('**/management/api/v1/**', async route => {
      const req = route.request(), url = new URL(req.url())
      calls.push({ method: req.method(), path: url.pathname, query: url.search })
      if (url.pathname.endsWith('/me')) return route.fulfill({ json: { username: 'admin', csrfToken: 'csrf-secret' } })
      if (url.pathname.endsWith('/scopes')) return route.fulfill({ json: { items: [
        { id: 'org-100', name: '第一机构', database: 'warehouse', companyId: '100' },
        { id: 'org-200', name: '第二机构', database: 'warehouse', companyId: '200' },
      ], nextCursor: null } })
      if (req.method() === 'POST') {
        posts++
        const body = req.postDataJSON()
        if (req.headers()['x-csrf-token'] !== 'csrf-secret' || body.expectedVersion !== 1 || body.companyId !== '100') throw Error('unexpected decision')
        const cached = await page.evaluate(() => Object.values(sessionStorage).some(value => value.includes('issue-rate') && value.includes('expectedVersion')))
        if (!cached) throw Error('decision not cached before POST')
        committed = { ...issue, version: 2, review: { ...issue.review, status: body.status, decisionReason: body.decisionReason }, proposal: body.proposal }
        return route.abort('failed')
      }
      if (url.searchParams.get('companyId') === '200') return route.fulfill({ json: { items: [], nextCursor: null } })
      return route.fulfill({ json: { items: [committed ?? issue], nextCursor: null } })
    })
    await page.goto('http://127.0.0.1:5188/management/report-issues?database=warehouse&companyId=100')
    await page.getByRole('button', { name: '查看并裁定', exact: true }).click()
    await page.getByLabel('采纳，登记候选改动', { exact: true }).check()
    await page.getByLabel('裁定理由', { exact: true }).fill('原始行合计证明平均比率有偏。')
    await page.getByLabel('候选改动', { exact: true }).fill('将平均执行率改为实际合计除以预算合计；正式规则需另行发布。')
    await page.getByLabel('原始反例与预期结果', { exact: true }).fill('预算100、200，实际90、100；错误均值70%，正确比率190/300=63.33%。')
    await page.getByRole('button', { name: '确认登记裁定', exact: true }).focus()
    await page.screenshot({ path: `${directory}/decision-${width}.png`, fullPage: true, animations: 'disabled' })
    const scan = async () => {
      await page.addScriptTag({ path: fileURLToPath(new URL('../node_modules/axe-core/axe.min.js', import.meta.url)) })
      return page.evaluate(async () => (await window.axe.run('main')).violations.filter(v => ['serious', 'critical'].includes(v.impact)).map(v => v.id))
    }
    const before = await scan()
    await page.keyboard.press('Enter')
    await page.getByText('裁定结果待确认', { exact: false }).waitFor()
    const focus = await page.evaluate(() => document.activeElement?.textContent)
    await page.reload()
    await page.getByRole('button', { name: '读取原裁定结果', exact: true }).waitFor()
    if (posts !== 1) throw Error('reopen resent decision')
    // 同库不同机构不共享本地待确认裁定。
    await page.getByRole('combobox', { name: '当前组织', exact: true }).click()
    await page.getByText('第二机构', { exact: true }).click()
    await page.waitForURL(url => url.searchParams.get('companyId') === '200', { timeout: 5000 }).catch(async error => { await page.screenshot({ path: `${directory}/scope-debug-${width}.png`, fullPage: true, animations: 'disabled' }); console.log('scope URL', page.url(), await page.locator('body').innerText()); throw error })
    await page.locator('.ant-empty-description').filter({ hasText: '暂无数据' }).waitFor()
    if (await page.getByRole('button', { name: '读取原裁定结果', exact: true }).count()) throw Error('cross-organization pending decision')
    await page.getByRole('combobox', { name: '当前组织', exact: true }).click()
    await page.getByText('第一机构', { exact: true }).click()
    await page.waitForURL(url => url.searchParams.get('companyId') === '100', { timeout: 5000 })
    await page.getByRole('button', { name: '读取原裁定结果', exact: true }).click()
    await page.getByText('已确认原裁定生效', { exact: false }).waitFor()
    await page.screenshot({ path: `${directory}/accepted-${width}.png`, fullPage: true, animations: 'disabled' })
    const result = { width, posts, focus, overflow: await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), seriousOrCritical: [...before, ...await scan()], calls }
    results.push(result)
    if (posts !== 1 || focus !== '读取原裁定结果' || result.overflow || result.seriousOrCritical.length) throw Error(JSON.stringify(result))
    await page.close()
  }
  await writeFile(`${directory}/browser-evidence.json`, JSON.stringify({ scope: '实际ManagementApp与受控HTTP；不替代真实管理PG端到端验收', results }, null, 2))
  console.log(JSON.stringify(results))
} finally { await browser.close() }
