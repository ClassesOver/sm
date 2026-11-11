import { chromium } from 'playwright'
import { readFile, mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const directory = fileURLToPath(new URL('../../../../docs/superpowers/reports/artifacts/2026-11-11-report-issue-regression-ui/management-ui', import.meta.url))
await mkdir(directory, { recursive: true })
const html = (await readFile(new URL('../management.html', import.meta.url), 'utf8')).replace('src="/src/', 'src="/management/src/')
const browser = await chromium.launch({ headless: true })
const results = []
try {
  for (const width of [1440, 1280, 768, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 1100 } })
    const correctedVersions = [{ assetType: 'metric', assetId: 'execution-rate', revision: 2 }]
    const issue = { basisId: 'basis-original', reportId: 'report-original', revision: 1, version: 2,
      review: { issueId: 'issue-rate', objectRefs: ['fact-rate'], category: 'calculation', description: '请核对执行率的计算方法。',
        status: 'accepted', decisionReason: '已关联正式修复版本，等待回归核验。', correctedVersions },
      proposal: { changeSummary: '先汇总再相除', counterexample: '独立核对190/300应为63.33%' } }
    let posts = 0, saved = null
    const calls = []
    await page.route('**/management/report-issues?**', route => route.fulfill({ contentType: 'text/html', body: html }))
    await page.route('**/management/api/v1/**', async route => {
      const req = route.request(), url = new URL(req.url())
      calls.push({ method: req.method(), path: url.pathname, query: url.search })
      if (url.pathname.endsWith('/me')) return route.fulfill({ json: { username: 'admin', csrfToken: 'synthetic-csrf' } })
      if (url.pathname.endsWith('/scopes')) return route.fulfill({ json: { items: [
        { id: 'org100', database: 'warehouse', companyId: '100', name: '第一机构' },
        { id: 'org200', database: 'warehouse', companyId: '200', name: '第二机构' }], nextCursor: null } })
      if (url.pathname.endsWith('/regression-targets')) return route.fulfill({ json: { issueVersion: 2, nextCursor: null, items: [{
        targetRunId: 'fixed-run', targetReportRevision: 'initial', calculationReceiptId: 'fixed-calculation', basisId: 'basis-fixed',
        available: true, reason: '', goal: '本月预算执行核对', metricName: '执行率', metricVersion: { metricId: 'execution-rate', revision: 2 },
        period: { start: '2026-11-01', end: '2026-12-01' }, facts: [
          { factId: 'fact-A', unit: '%', dimensions: [{ dimensionId: 'project', value: 'A' }] },
          { factId: 'fact-B', unit: '%', dimensions: [{ dimensionId: 'project', value: 'B' }] }] }] } })
      if (req.method() === 'POST') {
        posts++
        const { scopeDatabase, companyId, ...request } = req.postDataJSON()
        if (!url.pathname.endsWith('/regressions') || companyId !== '100' || scopeDatabase !== 'warehouse'
          || request.expectedIssueVersion !== 2 || req.headers()['x-csrf-token'] !== 'synthetic-csrf'
          || request.assertions.length !== 2 || request.assertions[0].expectedValue !== '70'
          || request.assertions[1].expectedValue !== null || request.assertions[1].expectedIssueCodes[0] !== 'zero_denominator') throw Error('unexpected regression request')
        const cached = await page.evaluate(id => Object.values(sessionStorage).some(value => value.includes(id) && value.includes('zero_denominator')), request.requestId)
        if (!cached) throw Error('full regression not cached before POST')
        saved = { receiptId: 'issue-regression-synthetic', issueId: 'issue-rate', request, correctedVersions,
          status: 'failed', verificationLevel: 'snapshot_recomputed', businessApproval: 'not_performed', createdAt: '2026-11-11T00:00:00Z',
          comparisons: request.assertions.map((assertion, index) => ({ assertion, matches: index === 1,
            actual: { factId: assertion.factId, status: index === 0 ? 'computed' : 'unavailable', value: index === 0 ? '63.3333333333333333' : null,
              unit: '%', issueCodes: index === 0 ? [] : ['zero_denominator'] } })) }
        return route.abort('failed')
      }
      if (url.pathname.endsWith('/regressions')) return route.fulfill({ json: { items: saved ? [saved] : [], nextCursor: null } })
      return route.fulfill({ json: { items: url.searchParams.get('companyId') === '200' ? [] : [issue], nextCursor: null } })
    })
    await page.goto('http://127.0.0.1:5188/management/report-issues?database=warehouse&companyId=100')
    await page.getByRole('button', { name: '查看并裁定', exact: true }).click()
    await page.getByRole('button', { name: '新建回归核验', exact: true }).click()
    await page.getByRole('button', { name: '选择此计算', exact: true }).click()
    const form = page.locator('#issue-regression')
    await form.getByLabel('反例标识', { exact: true }).fill('rate-original-counterexample')
    await form.getByLabel('独立预期依据', { exact: true }).fill('原始预算100、200，执行90、100；先核对旧错误预期70%，验证必须保留失败。')
    await form.locator('fieldset').nth(0).getByRole('radio', { name: '可计算', exact: true }).check()
    if (await form.getByLabel('独立预期值', { exact: true }).inputValue() !== '') throw Error('actual prefilled as expected')
    await form.getByLabel('独立预期值', { exact: true }).fill('70')
    await form.getByLabel('比较小数位（留空为精确比较）', { exact: true }).fill('2')
    await form.locator('fieldset').nth(1).getByRole('radio', { name: '不可计算', exact: true }).check()
    await form.getByLabel('预期不可计算原因标识（逗号分隔）', { exact: true }).fill('zero_denominator')
    await form.getByRole('button', { name: '确认快照核验并登记', exact: true }).focus()
    await page.screenshot({ path: `${directory}/expectations-${width}.png`, fullPage: true, animations: 'disabled' })
    const scan = async () => {
      await page.addScriptTag({ path: fileURLToPath(new URL('../node_modules/axe-core/axe.min.js', import.meta.url)) })
      return page.evaluate(async () => (await window.axe.run('main')).violations.filter(item => ['serious', 'critical'].includes(item.impact)).map(item => ({ id: item.id, nodes: item.nodes.map(node => ({ target: node.target, summary: node.failureSummary })) })))
    }
    const before = await scan()
    await page.keyboard.press('Enter')
    await page.getByText('核验登记结果待确认', { exact: false }).waitFor()
    const focus = await page.evaluate(() => document.activeElement?.textContent)
    await page.reload()
    await page.getByRole('button', { name: '查看并裁定', exact: true }).click()
    await page.getByRole('button', { name: '读取原回归结果', exact: true }).waitFor()
    if (posts !== 1) throw Error('reload resent regression')
    await page.getByRole('combobox', { name: '当前组织', exact: true }).click()
    await page.getByText('第二机构', { exact: true }).click()
    await page.waitForURL(url => url.searchParams.get('companyId') === '200')
    await page.locator('.ant-empty-description').filter({ hasText: '暂无数据' }).waitFor()
    if (await page.getByRole('button', { name: '读取原回归结果', exact: true }).count()) throw Error('foreign scope displayed pending regression')
    await page.getByRole('combobox', { name: '当前组织', exact: true }).click()
    await page.getByText('第一机构', { exact: true }).click()
    await page.waitForURL(url => url.searchParams.get('companyId') === '100')
    await page.getByRole('button', { name: '查看并裁定', exact: true }).click()
    await page.getByRole('button', { name: '读取原回归结果', exact: true }).click()
    await page.getByText('已确认原回归核验登记', { exact: false }).waitFor()
    await page.getByText('快照核验不符合预期', { exact: true }).first().waitFor()
    await page.screenshot({ path: `${directory}/failed-${width}.png`, fullPage: true, animations: 'disabled' })
    const result = { width, posts, focus, overflow: await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),
      seriousOrCritical: [...before, ...await scan()], calls }
    results.push(result)
    if (posts !== 1 || focus !== '读取原回归结果' || result.overflow || result.seriousOrCritical.length) throw Error(JSON.stringify(result))
    await page.close()
  }
  await writeFile(`${directory}/browser-evidence.json`, JSON.stringify({ scope: '实际ManagementApp与受控HTTP，失败合成数据；不替代真实PG/业务签认', results }, null, 2))
  console.log(JSON.stringify(results))
} finally { await browser.close() }
