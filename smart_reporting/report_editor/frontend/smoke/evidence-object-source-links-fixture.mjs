// 只读正文验证指标数据格、图表和分析入口；来源均来自登记的fixture契约。
import assert from 'node:assert/strict'
import { chromium } from 'playwright'
const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } })
  let writes = 0
  let phase = 'valid'
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/document', async route => {
    if (route.request().method() !== 'GET') { writes++; return route.abort() }
    const response = await route.fetch()
    const payload = await response.json()
    payload.markdown = '# 收入[[analysis:analysis-fixture-001]]\n\n[[table:tbl-1]]\n\n| 期间 | 收入 |\n| --- | --- |\n| 本期 | 12,450 |\n\n![收入趋势](chart-fixture.svg)\n'
    if (phase === 'stale') payload.markdown = payload.markdown.replace('12,450', '12,451')
    await route.fulfill({ response, json: payload })
  })
  await page.route('**/asset/chart-fixture.svg', route => route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="140"><rect width="300" height="140" fill="#e0f2fe"/><path d="M20 110 L90 70 L170 85 L270 20" fill="none" stroke="#2563eb" stroke-width="4"/></svg>' }))
  await page.route('**/api/sources', async route => {
    const response = await route.fetch()
    const payload = await response.json()
    payload.facts = [{ analysisId: 'analysis-fixture-001', factId: 'fact-fixture-001', factKind: 'metric', name: '收入金额', label: '收入金额', displayValue: 12450, unit: '万元', datasetIds: ['dataset-fixture-001'] }]
    payload.subjects = [{ subjectId: 'sub-fixture-001', subjectKind: 'table_cell', locator: { tableId: 'tbl-1', rowKey: 'current', columnKey: '收入' }, factRefs: [{ analysisId: 'analysis-fixture-001', factId: 'fact-fixture-001' }], computationId: 'comp-fixture-001' }]
    payload.subjects.push({ ...payload.subjects[0], subjectId: 'sub-fixture-002' })
    await route.fulfill({ response, json: payload })
  })
  await page.route('**/api/sources/validate', async route => {
    const payload = route.request().postDataJSON()
    await route.fulfill({ json: { draftSha256: payload.draftSha256, subjects: [], summary: { valid: 0, stale: 0, unbound: 0 },
      tables: phase !== 'unbound' ? [{ tableId: 'tbl-1', cells: { valid: phase === 'valid' ? 1 : 0, stale: phase === 'stale' ? 1 : 0, unbound: 0 }, locations: [{ rowKey: 'current', columnKey: '收入', rowIndex: 0, columnIndex: 1, rowLabel: '本期', text: phase === 'stale' ? '12,451' : '12,450', status: phase }] }] : [],
      charts: [{ chartId: 'chart-fixture', imagePath: 'chart-fixture.svg', locationSource: phase === 'unbound' ? null : 'chart-fixture.svg', status: phase }],
    } })
  })
  await page.route('**/api/charts', route => route.fulfill({ json: { available: true, charts: [{ chartId: 'chart-fixture', datasetIds: ['dataset-fixture-001'], datasetIdsRegistered: true, plotDataFileCount: 1, plotDataKind: 'chart-input/v1', transformNotes: [], imageSize: 100 }] } }))
  await page.route('**/api/charts/chart-fixture/source?*', route => route.fulfill({ json: {
    available: true, chartId: 'chart-fixture', datasetIds: ['dataset-fixture-001'], computationId: 'comp-fixture-001', transformNotes: [], image: { size: 100, sha256: 'a'.repeat(64) },
    plotData: [{ fileResourceId: 'plot-1', role: 'main', columns: ['收入'], rowCount: 1, offset: 0, limit: 20, rows: [[12450]], truncated: false }],
  } }))
  await page.goto('http://127.0.0.1:4173/reports/v1/editor/fixture-report/1', { waitUntil: 'networkidle' })
  const editor = page.locator('.ProseMirror')
  const raw = await editor.textContent()
  const metric = page.locator('td .report-object-source-marker')
  const chart = page.locator('.report-object-source-marker[data-marker-kind="chart"]')
  await metric.waitFor()
  await chart.waitFor()
  await page.screenshot({ path: '/home/junge/pros/smart_reporting/output/report-editor-object-source-links-390.png' })
  assert.equal(await metric.getAttribute('data-marker-count'), '2')
  await metric.press('Enter')
  await page.locator('.report-source-picker').getByRole('button', { name: '引用来源 1', exact: true }).click()
  await page.locator('.evidence-subject-links').waitFor()
  await page.locator('.evidence-subject-links button').filter({ hasText: '收入金额' }).click()
  await page.locator('.evidence-object-title').filter({ hasText: '收入金额' }).waitFor()
  await page.getByRole('tab', { name: '报告正文', exact: true }).click()
  await chart.press('Space')
  await page.locator('.evidence-table').getByText('12450', { exact: true }).waitFor()
  await page.getByRole('button', { name: '切换到关系列表', exact: true }).click()
  await page.locator('.evidence-relation-list button').filter({ hasText: '季度收入快照' }).click()
  await page.locator('.evidence-table').getByText('4230', { exact: true }).waitFor()
  await page.getByRole('tab', { name: '报告正文', exact: true }).click()
  await page.locator('[data-marker-kind="analysis"]').click()
  await page.locator('.evidence-analysis-overview [data-fact-id="fact-fixture-001"]').click()
  await page.locator('.evidence-object-title').filter({ hasText: '收入金额' }).waitFor()
  await page.getByRole('tab', { name: '报告正文', exact: true }).click()
  assert.equal(await editor.textContent(), raw)
  phase = 'stale'
  await page.reload({ waitUntil: 'networkidle' })
  await chart.waitFor({ timeout: 3000 })
  assert.equal(await chart.getAttribute('data-marker-state'), 'stale')
  assert.equal(await metric.getAttribute('data-marker-state'), 'stale')
  assert.match(await chart.getAttribute('aria-label'), /待复核/)
  assert.match(await metric.getAttribute('aria-label'), /待复核/)
  assert.equal(await metric.evaluate(element => getComputedStyle(element).color), 'rgb(180, 83, 9)')
  assert.equal(await chart.evaluate(element => getComputedStyle(element).color), 'rgb(180, 83, 9)')
  await page.screenshot({ path: '/home/junge/pros/smart_reporting/output/report-editor-source-stale-390.png' })
  await chart.press('Enter')
  await page.locator('.evidence-table').getByText('12450', { exact: true }).waitFor()
  await page.locator('[data-evidence="back"]').click()
  await page.locator('.evidence-table').getByText('4230', { exact: true }).waitFor()
  await page.getByRole('tab', { name: '报告正文', exact: true }).click()
  assert.ok((await editor.textContent()).includes('12,451'))
  await metric.press('Enter')
  await page.locator('.report-source-picker').getByRole('button', { name: '引用来源 1', exact: true }).click()
  await page.locator('.evidence-subject-links button').filter({ hasText: '收入金额' }).click()
  await page.locator('.evidence-object-title').filter({ hasText: '收入金额' }).waitFor()
  assert.ok((await page.locator('#evidence-workspace').textContent()).includes('12,450'), '改值后仍查看冻结登记事实')
  await page.getByRole('tab', { name: '报告正文', exact: true }).click()
  assert.ok((await editor.textContent()).includes('12,451'))
  phase = 'unbound'
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(1000)
  await page.waitForTimeout(200)
  assert.equal(await page.locator('.report-object-source-marker').count(), 0, '位置失效时不提供错误关联')
  assert.equal(writes, 0)
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ metric: 'passed', chart: 'passed', dataset: 'passed', analysis: 'passed', grouped: 'passed', stale: 'passed', deepLink: 'passed', history: 'passed', writes, errors }))
} finally { await browser.close() }
