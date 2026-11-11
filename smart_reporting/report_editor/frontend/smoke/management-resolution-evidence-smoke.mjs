import { chromium } from 'playwright'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const directory = fileURLToPath(new URL('../../../../docs/superpowers/reports/artifacts/2026-11-11-report-issue-content-binding/management-ui', import.meta.url))
await mkdir(directory, { recursive: true })
const html = (await readFile(new URL('../management.html', import.meta.url), 'utf8')).replace('src="/src/', 'src="/management/src/')
const browser = await chromium.launch({ headless: true })
const results = []
try {
  for (const width of [1440, 1280, 768, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 1100 } })
    const correctedVersions = [{ assetType: 'metric', assetId: 'budget', revision: 2 }]
    const issue = { basisId: 'basis-original', reportId: 'report-original', revision: 1, version: 2,
      review: { issueId: 'issue-budget', objectRefs: ['fact-budget'], category: 'calculation', description: '核对预算合计与原始字段。',
        status: 'accepted', decisionReason: '已采纳，正式版本已关联，等待证据核验。', correctedVersions }, proposal: null }
    const assertion = { factId: 'fact-budget', expectedStatus: 'computed', expectedValue: '300', unit: 'CNY', decimalPlaces: null, expectedIssueCodes: [] }
    const receipt = { receiptId: 'regression-passed', issueId: 'issue-budget', correctedVersions, status: 'passed',
      verificationLevel: 'snapshot_recomputed', businessApproval: 'not_performed', createdAt: '2026-11-11T00:00:00Z',
      request: { requestId: 'request-budget', expectedIssueVersion: 2, caseId: 'budget-total', targetRunId: 'fixed-run',
        targetReportRevision: 'initial', calculationReceiptId: 'calculation-budget', expectationReason: '原始两行100与200合计300', assertions: [assertion] },
      comparisons: [{ assertion, actual: { factId: 'fact-budget', value: '300', status: 'computed', unit: 'CNY', issueCodes: [] }, matches: true }] }
    let posts = 0, fullChecks = 0
    await page.route('**/management/report-issues?**', route => route.fulfill({ contentType: 'text/html', body: html }))
    await page.route('**/management/api/v1/**', async route => {
      const req = route.request(), url = new URL(req.url())
      if (url.pathname.endsWith('/me')) return route.fulfill({ json: { username: 'admin', csrfToken: 'synthetic-csrf' } })
      if (url.pathname.endsWith('/scopes')) return route.fulfill({ json: { items: [
        { id: 'org100', name: '第一机构', database: 'warehouse', companyId: '100' },
        { id: 'org200', name: '第二机构', database: 'warehouse', companyId: '200' }], nextCursor: null } })
      if (req.method() === 'POST') {
        posts++
        const body = req.postDataJSON()
        if (body.expectedIssueVersion !== 2 || body.companyId !== '100' || body.regressionReceiptIds.join() !== 'regression-passed') throw Error('unexpected check identity')
        if (url.pathname.endsWith('/resolution-evidence-check')) { fullChecks++; return route.fulfill({ json: {
          issueId: 'issue-budget', issueVersion: 2, checkedAt: '2026-11-11T00:00:00Z', regressionEvidenceReady: true,
          businessApproval: 'not_performed', issueClosed: false, issues: [], checks: [{ receiptId: 'regression-passed', status: 'passed', issues: [] }],
          originalEvidenceReady: false, originalChecks: [{ documentId: 'budget-rules', revision: 2, status: 'unavailable',
            issues: [{ code: 'management_document_original_unavailable', message: '原件缺失或身份已变化，暂时无法读取。' }] }],
          reportRelationships: [{ receiptId: 'regression-passed', targetRunId: 'adopted-run', targetBasisId: 'basis-adopted',
            parentBasisId: 'basis-original', status: 'verified', deliveryVerified: fullChecks > 1, issues: [],
            outputRevision: 3, validationPassed: false, factPresentationVerified: fullChecks > 1,
            coveredFactIds: fullChecks > 1 ? ['fact-budget'] : [], missingFactIds: fullChecks > 1 ? [] : ['fact-budget'],
            contentIssues: fullChecks > 1 ? [] : [{ code: 'management_issue_report_fact_uncovered', message: '尚未呈现回归事实。' }],
            deliveryArtifacts: fullChecks > 1 ? ['pdf', 'docx'].map(format => ({ format, path: `report.${format}`, size: 123, sha256: 'a'.repeat(64) })) : [],
            deliveryIssues: fullChecks > 1 ? [] : [{ code: 'management_issue_delivery_incomplete', message: '新报告尚未完成。' }] }] } }) }
        if (!url.pathname.endsWith('/regression-evidence-check') || body.expectedIssueVersion !== 2
          || body.companyId !== '100' || body.regressionReceiptIds.join() !== 'regression-passed') throw Error('unexpected check')
        return route.fulfill({ json: { issueId: 'issue-budget', issueVersion: 2, checkedAt: '2026-11-11T00:00:00Z',
          regressionEvidenceReady: false, businessApproval: 'not_performed', issueClosed: false,
          issues: [{ code: 'management_issue_regression_incomplete', message: '通过的回归尚未覆盖全部关联修复指标。' }],
          checks: [{ receiptId: 'regression-passed', status: 'failed', issues: [{ code: 'metric_snapshot_invalid', message: '回归快照缺失或不可读取。' }] }] } })
      }
      if (url.pathname.endsWith('/regressions')) return route.fulfill({ json: { items: [receipt], nextCursor: null } })
      return route.fulfill({ json: { items: url.searchParams.get('companyId') === '200' ? [] : [issue], nextCursor: null } })
    })
    await page.goto('http://127.0.0.1:5188/management/report-issues?database=warehouse&companyId=100')
    await page.getByRole('button', { name: '查看并裁定', exact: true }).click()
    const section = page.getByRole('region', { name: '关闭前回归证据检查', exact: true })
    await section.getByRole('checkbox', { name: '检查budget-total的当前证据', exact: true }).check()
    await section.getByRole('button', { name: '检查所选回归的当前证据', exact: true }).focus()
    await page.keyboard.press('Enter')
    await section.getByText('回归快照缺失或不可读取。', { exact: false }).waitFor()
    if (posts !== 1 || !await page.getByText('已采纳，待修复', { exact: true }).count()) throw Error('unexpected issue mutation')
    await section.getByRole('button', { name: '检查原件与新报告关系', exact: true }).focus({ timeout: 5000 }).catch(async error => {
      await page.screenshot({ path: `${directory}/failure-${width}.png`, fullPage: true });
      console.error(JSON.stringify({ width, url: page.url(), body: (await page.locator('body').innerText()).slice(-5000), buttons: await page.locator('button').allTextContents(), accessibility: await section.ariaSnapshot(), buttonHtml: await section.locator('button').evaluateAll(nodes => nodes.map(node => node.outerHTML)) })); throw error
    })
    await page.keyboard.press('Enter')
    await section.getByText('原件缺失或身份已变化，暂时无法读取。', { exact: false }).waitFor()
    await section.getByText('新依据父链已核对', { exact: true }).waitFor()
    await section.getByText('报告最终交付尚未核验', { exact: false }).waitFor()
    if (posts !== 2) throw Error('unexpected expanded evidence request count')
    await page.screenshot({ path: `${directory}/current-unavailable-${width}.png`, fullPage: true, animations: 'disabled' })
    await section.getByRole('button', { name: '检查原件与新报告关系', exact: true }).focus()
    await page.keyboard.press('Enter')
    await section.getByText('新报告修订 3 的请求格式文件本次可读且身份匹配。', { exact: true }).waitFor()
    await section.getByText('原交付验收未通过；文件可读不代表验收或业务签认通过。', { exact: true }).waitFor()
    await section.getByText('PDF · 文件身份已核对', { exact: true }).waitFor()
    await section.getByText('DOCX · 文件身份已核对', { exact: true }).waitFor()
    await section.getByText('回归计算的全部根指标事实已在本次正文或冻结附表中核对。', { exact: true }).waitFor()
    await section.getByText('此项不证明业务解释、图表或全部导出内容一致，仍需业务签认。', { exact: true }).waitFor()
    if (posts !== 3 || !await page.getByText('已采纳，待修复', { exact: true }).count()) throw Error('delivery check closed issue')
    await page.screenshot({ path: `${directory}/delivery-readable-${width}.png`, fullPage: true, animations: 'disabled' })
    await page.addScriptTag({ path: fileURLToPath(new URL('../node_modules/axe-core/axe.min.js', import.meta.url)) })
    const seriousOrCritical = await page.evaluate(async () => (await window.axe.run('main')).violations.filter(item => ['serious', 'critical'].includes(item.impact)).map(item => item.id))
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
    await page.getByRole('combobox', { name: '当前组织', exact: true }).click()
    await page.getByText('第二机构', { exact: true }).click()
    await page.locator('.ant-empty-description').filter({ hasText: '暂无数据' }).waitFor()
    if (await page.getByText('回归快照缺失或不可读取。', { exact: false }).count()) throw Error('foreign organization retained evidence')
    await page.reload()
    if (posts !== 3) throw Error('reload auto-rechecked')
    const result = { width, posts, overflow, seriousOrCritical }
    results.push(result)
    if (overflow || seriousOrCritical.length) throw Error(JSON.stringify(result))
    await page.close()
  }
  await writeFile(`${directory}/browser-evidence.json`, JSON.stringify({ scope: '实际ManagementApp与受控HTTP；不等于真实PG连续验收或业务签认', results }, null, 2))
  console.log(JSON.stringify(results))
} finally { await browser.close() }
