// 登记事实摘要：跨分析同名身份、零值、负变化额和缺值；单击不加载详情。
import assert from 'node:assert/strict'
import { chromium } from 'playwright'
const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  const errors = [], requested = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/sources', route => route.fulfill({ json: {
    available: true, datasets: [], subjects: [], drilldown: { enabled: false, metrics: [], subjects: [] }, facts: [
      { analysisId: 'analysis_001', factId: 'root', factKind: 'metric', name: '事实产出', label: '事实产出', displayValue: 1, datasetIds: [] },
      { analysisId: 'analysis_001', factId: 'shared', factKind: 'metric', name: '收入金额', label: '收入金额', displayValue: 0, unit: '万元', periodStart: '2025-01-01', periodEnd: '2025-11-01', periodRoles: ['current'], datasetIds: [] },
      { analysisId: 'analysis_002', factId: 'shared', factKind: 'comparison', name: '收入金额', label: '收入金额', displayValue: -514421873, unit: '元', periodStart: '2024-11-01', periodRoles: ['yoy'], datasetIds: [] },
    ],
  } }))
  await page.route('**/api/facts/**', route => {
    const path = new URL(route.request().url()).pathname
    requested.push(path.split('/api/facts/')[1])
    return route.fulfill({ json: { analysisId: 'analysis_001', factId: 'root', factKind: 'metric', displayValue: 1, entry: {}, warnings: [],
      inputFactRefs: [{ analysisId: 'analysis_001', factId: 'shared' }, { analysisId: 'analysis_002', factId: 'shared' }, { analysisId: 'analysis_001', factId: 'unknown' }],
    } })
  })
  await page.goto('http://127.0.0.1:4173/reports/v1/editor/fixture-report/1', { waitUntil: 'networkidle' })
  await page.locator('[data-action="sources"]').click()
  await page.locator('.evidence-directory-item').filter({ hasText: '事实产出' }).click()
  await page.locator('.evidence-graph-3d canvas').waitFor()
  const choose = async (id, value, period) => {
    await page.getByRole('combobox', { name: '选择 3D 节点预览' }).selectOption(id)
    await page.locator('.evidence-preview-value').waitFor()
    assert.equal(await page.locator('.evidence-preview-value').textContent(), value)
    assert.equal(await page.locator('.evidence-preview-period').textContent(), period)
    assert.equal(await page.locator('.evidence-preview-summary strong').textContent(), '预览：收入金额')
    assert.ok((await page.locator('.evidence-object-title').textContent()).includes('事实产出'))
  }
  await choose('fact:analysis_001/shared', '登记值 0 万元', '本期 · 2025-01-01 — 2025-11-01')
  await choose('fact:analysis_002/shared', '登记变化额 -514,421,873 元', '同比基期 · 2024-11-01')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '查看关系图', exact: true }).click()
  await page.waitForTimeout(300)
  await page.locator('.evidence-relations').screenshot({ path: '/home/junge/pros/smart_reporting/output/report-editor-fact-preview-390.png' })
  const geometry = await page.locator('.evidence-preview').evaluate(element => {
    const box = element.getBoundingClientRect()
    return { width: box.width, height: box.height, scrollHeight: element.scrollHeight, clientHeight: element.clientHeight, overflow: getComputedStyle(element).overflowY }
  })
  assert.ok(geometry.width <= 390)
  assert.ok(geometry.scrollHeight <= geometry.clientHeight + 1, '手机事实摘要及操作完整可见')
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
  await page.getByRole('button', { name: '切换到 2D 关系图', exact: true }).click()
  assert.equal(await page.locator('.evidence-preview-value').textContent(), '登记变化额 -514,421,873 元')
  await page.getByRole('button', { name: '切换到 3D 关系图', exact: true }).click()
  await page.getByRole('combobox', { name: '选择 3D 节点预览' }).selectOption('fact:analysis_001/unknown')
  assert.equal(await page.locator('.evidence-preview-value').count(), 0, '未登记数值不推断')
  assert.equal(await page.locator('.evidence-preview-period').count(), 0)
  assert.deepEqual(requested, ['analysis_001/root'])
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ zero: 'passed', comparison: 'passed', identity: 'passed', unknown: 'passed', mode: 'passed', geometry, requested, errors }))
} finally { await browser.close() }
