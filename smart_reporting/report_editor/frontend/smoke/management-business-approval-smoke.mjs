import { chromium } from 'playwright'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const directory = fileURLToPath(new URL('../../../../docs/superpowers/reports/artifacts/2026-11-11-report-business-approval-ui/browser', import.meta.url))
await mkdir(directory, { recursive: true })
const html = (await readFile(new URL('../management.html', import.meta.url), 'utf8')).replace('src="/src/', 'src="/management/src/')
const sorted = value => Array.isArray(value) ? value.map(sorted) : value && typeof value === 'object'
  ? Object.fromEntries(Object.keys(value).sort().map(key => [key, sorted(value[key])])) : value
const hash = value => createHash('sha256').update(JSON.stringify(sorted(value)).replace(/[\u0080-\uffff]/g, char => '\\u' + char.charCodeAt(0).toString(16).padStart(4, '0'))).digest('hex')
const browser = await chromium.launch({ headless: true })
const results = []
try {
  for (const width of [1440, 1280, 768, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 1100 } })
    page.setDefaultTimeout(10000)
    const fixes = [{ assetType: 'metric', assetId: 'budget', revision: 2 }]
    const issue = { basisId: 'basis-original', reportId: 'report-original', revision: 1, version: 2,
      review: { issueId: 'issue-budget', objectRefs: ['fact-budget'], category: 'calculation', description: '预算合计应为300，请核对原始两行。',
        status: 'accepted', decisionReason: '已采纳，正式修复已发布，等待独立预期签认。', correctedVersions: fixes }, proposal: null }
    const assertion = { factId: 'fact-budget', expectedStatus: 'computed', expectedValue: '300', unit: 'CNY', decimalPlaces: null, expectedIssueCodes: [] }
    const regression = { receiptId: 'regression-passed', issueId: 'issue-budget', correctedVersions: fixes, status: 'passed',
      verificationLevel: 'snapshot_recomputed', businessApproval: 'not_performed', createdAt: '2026-11-11T00:00:00Z',
      request: { requestId: 'original-regression', expectedIssueVersion: 2, caseId: 'budget-total', targetRunId: 'fixed-run', targetReportRevision: 'initial',
        calculationReceiptId: 'calculation-1', expectationReason: '独立预算100+200=300', assertions: [assertion] },
      comparisons: [{ assertion, actual: { factId: 'fact-budget', value: '300', status: 'computed', unit: 'CNY', issueCodes: [] }, matches: true }] }
    const locator = { kind: 'text_lines', lineStart: 1, lineEnd: 1, page: null, paragraph: null, table: null, row: null, column: null }
    const quote = '合成独立对账：项目A预算100元，项目B预算200元，预算合计300元。'
    let saved = null, signingPosts = 0, checkPosts = 0
    await page.route('**/management/report-issues?**', route => route.fulfill({ contentType: 'text/html', body: html }))
    await page.route('**/management/api/v1/**', async route => {
      const req = route.request(), url = new URL(req.url())
      if (url.pathname.endsWith('/me')) return route.fulfill({ json: { username: 'admin', csrfToken: 'synthetic-csrf' } })
      if (url.pathname.endsWith('/scopes')) return route.fulfill({ json: { items: [
        { id: 'org100', name: '第一机构', database: 'warehouse', companyId: '100' }, { id: 'org200', name: '第二机构', database: 'warehouse', companyId: '200' }], nextCursor: null } })
      if (url.pathname.endsWith('/approval-source-options')) return route.fulfill({ json: { items: [{ documentId: 'independent-budget', revision: 1, name: '独立预算对账', available: true, reason: '' }], nextCursor: null } })
      if (url.pathname.endsWith('/business-documents/independent-budget')) return route.fulfill({ json: { documentId: 'independent-budget', revisions: [
        { revision: 1, reviewStatus: 'approved', ingestionStatus: 'ready', parseReceipt: { fragments: [{ locator, text: quote }] } }] } })
      if (req.method() === 'POST' && url.pathname.endsWith('/business-approvals')) {
        signingPosts++
        const { scopeDatabase, companyId, ...body } = req.postDataJSON()
        if (signingPosts !== 1 || scopeDatabase !== 'warehouse' || companyId !== '100' || body.decision !== 'approve_expected_values'
          || body.sources[0].quote !== quote || body.regressionReceiptIds.join() !== 'regression-passed') throw Error('wrong signing identity')
        saved = { receiptId: 'approval-saved', issueId: 'issue-budget', requestHash: hash(body),
          request: { ...body, sources: body.sources.map(({ quote: _quote, ...source }) => source) }, correctedVersions: fixes,
          approvedByUsername: 'admin', approvedByAccountId: 1, businessApproval: 'explicitly_approved', approvalScope: 'regression_expected_values',
          currentEvidenceStatus: 'not_checked', createdAt: '2026-11-11T00:00:00Z' }
        return route.abort('failed')
      }
      if (url.pathname.includes('/business-approvals/')) return route.fulfill({ json: saved })
      if (req.method() === 'POST' && url.pathname.endsWith('/resolution-evidence-check')) {
        checkPosts++
        const body = req.postDataJSON()
        if (body.businessApprovalRequestId !== saved.request.requestId || body.regressionReceiptIds.join() !== 'regression-passed') throw Error('wrong signoff check')
        return route.fulfill({ json: { issueId: 'issue-budget', issueVersion: 2, checkedAt: '2026-11-11T00:00:00Z',
          regressionEvidenceReady: true, businessApproval: 'explicitly_approved', businessApprovalReady: true,
          businessApprovalCheck: { requestId: saved.request.requestId, status: 'verified', issues: [], approvedByUsername: 'admin' },
          issueClosed: false, issues: [], checks: [{ receiptId: 'regression-passed', status: 'passed', issues: [] }],
          originalEvidenceReady: true, originalChecks: [{ documentId: 'independent-budget', title: '独立预算对账', revision: 1, status: 'readable', issues: [] }],
          deliveryReady: false, factPresentationReady: false, reportRelationships: [] } })
      }
      if (url.pathname.endsWith('/regressions')) return route.fulfill({ json: { items: [regression], nextCursor: null } })
      return route.fulfill({ json: { items: url.searchParams.get('companyId') === '200' ? [] : [issue], nextCursor: null } })
    })
    await page.goto('http://127.0.0.1:5188/management/report-issues?database=warehouse&companyId=100')
    await page.getByRole('button', { name: '查看并裁定', exact: true }).click()
    const signing = page.getByRole('region', { name: '业务预期签认', exact: true })
    await signing.getByRole('button', { name: '签认回归预期', exact: true }).click()
    await signing.getByRole('checkbox', { name: '签认budget-total的预期', exact: true }).check()
    await signing.getByRole('button', { name: '选择独立原件', exact: true }).click()
    await signing.getByRole('button', { name: '读取独立预算对账', exact: true }).click()
    await signing.getByRole('button', { name: '采用此原文位置', exact: true }).click()
    await signing.getByRole('textbox', { name: '签认理由与独立推导', exact: true }).fill('已核对独立对账A100+B200=300，签认所选回归全部预期，不批准整份报告。')
    await signing.getByRole('checkbox', { name: '明确签认所选回归预期', exact: true }).check()
    await signing.screenshot({ path: `${directory}/signing-form-${width}.png`, animations: 'disabled' })
    await signing.getByRole('button', { name: '确认签认并登记', exact: true }).focus()
    await page.keyboard.press('Enter')
    await signing.getByText('签认结果待确认', { exact: false }).waitFor()
    await page.reload()
    await page.getByRole('button', { name: '查看并裁定', exact: true }).click()
    await signing.getByRole('button', { name: '读取原签认结果', exact: true }).waitFor()
    if (!await signing.getByRole('button', { name: '读取原签认结果', exact: true }).evaluate(node => node === document.activeElement)) throw Error('recovery focus missing')
    await page.keyboard.press('Enter')
    await signing.getByText('已确认原签认登记', { exact: false }).waitFor()
    await signing.getByRole('button', { name: '用于本次关闭准备检查', exact: true }).click()
    await page.getByRole('button', { name: '检查原件与新报告关系', exact: true }).click()
    await page.getByText('所选回归预期的显式签认本次有效；不等于整报告批准，问题未关闭。', { exact: true }).waitFor()
    const section = page.getByRole('region', { name: '关闭前回归证据检查', exact: true })
    await section.screenshot({ path: `${directory}/current-signoff-${width}.png`, animations: 'disabled' })
    await page.addScriptTag({ path: fileURLToPath(new URL('../node_modules/axe-core/axe.min.js', import.meta.url)) })
    const seriousOrCritical = await page.evaluate(async () => (await window.axe.run('main')).violations.filter(item => ['serious', 'critical'].includes(item.impact)).map(item => item.id))
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
    await page.getByRole('combobox', { name: '当前组织', exact: true }).click()
    await page.getByText('第二机构', { exact: true }).click()
    await page.locator('.ant-empty-description').filter({ hasText: '暂无数据' }).waitFor()
    if (await page.getByRole('region', { name: '业务预期签认', exact: true }).count()) throw Error('foreign organization retained signoff')
    await page.reload()
    const result = { width, signingPosts, checkPosts, seriousOrCritical, overflow }
    results.push(result)
    if (signingPosts !== 1 || checkPosts !== 1 || overflow || seriousOrCritical.length) throw Error(JSON.stringify(result))
    await page.close()
  }
  await writeFile(`${directory}/browser-evidence.json`, JSON.stringify({ scope: '实际ManagementApp及受控HTTP，不替代真实PG连续业务签认', results }, null, 2))
  console.log(JSON.stringify(results))
} finally { await browser.close() }
