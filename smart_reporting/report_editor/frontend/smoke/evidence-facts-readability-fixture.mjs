// facts 可读性：已登记名称、期间、数值、筛选与比较口径；不修改正式报告。
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdir } from 'node:fs/promises'
import { chromium } from 'playwright'

const output = new URL('../../../../output/', import.meta.url)
await mkdir(output, { recursive: true })
const longName = process.env.REPORT_EDITOR_FACT_LONG_NAME === '1'
const analysisId = longName ? 'analysis_123456' : 'analysis_001'
const name = longName ? '医疗业务收入（覆盖主院区、东院区和新院区，包含住院及门诊结算，剔除跨期调整后的累计已结算收入）' : '各院区医疗业务收入'
const facts = [
  { factId: 'fact-current', factKind: 'metric', label: `指标 · ${name} · 本期 · 2025-01 — 2025-09`, name, periodRoles: ['current'], displayValue: 12450 },
  { factId: 'fact-baseline', factKind: 'metric', label: `指标 · ${name} · 同比基期 · 2024-01 — 2024-09`, name, periodRoles: ['yoy'], displayValue: 10000 },
  { factId: 'fact-comparison', factKind: 'comparison', label: `对比 · ${name} · 同比 · 2025-01 — 2025-09`, name, comparisonType: 'yoy', displayValue: 2450 },
].map((fact, index) => ({ ...fact, analysisId, datasetIds: [], unit: '万元', periodStart: index === 1 ? '2024-01' : '2025-01', periodEnd: index === 1 ? '2024-09' : '2025-09' }))
const markdown = `# 医院运营分析报告\n\n## 收入分析\n\n医疗收入为 12,450 万元。[[analysis:${analysisId}]]\n`
const browser = await chromium.launch({ headless: true })
try {
  const widths = longName ? [1280, 390, 320] : [1280, 390]
  for (const width of widths) {
    const page = await browser.newPage({ viewport: { width, height: width <= 390 ? 844 : 900 } })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.route('**/api/document', async route => {
      const response = await route.fetch()
      await route.fulfill({ response, json: { ...await response.json(), markdown, sha256: createHash('sha256').update(markdown).digest('hex') } })
    })
    await page.route('**/api/sources', route => route.fulfill({ json: { available: true, facts, subjects: [], datasets: [] } }))
    await page.route(`**/api/facts/${analysisId}/*`, route => {
      const fact = facts.find(item => route.request().url().endsWith(item.factId))
      const entry = fact.factKind === 'comparison'
        ? { field: name, comparisonType: 'yoy', currentTotal: 12450, baselineTotal: 10000, change: 2450, changeRate: 24.5, formula: '(currentTotal-baselineTotal)/abs(baselineTotal)*100%' }
        : { field: name, aggregation: 'sum', average: 1383.3, scope: { 院区: '东院、西院（仅含已结算业务）' }, formula: 'SUM(医疗业务收入) WHERE 结算状态 = 已结算' }
      return route.fulfill({ json: { ...fact, entry: { ...entry, unit: fact.unit, periodRoles: fact.periodRoles, periodStart: fact.periodStart, periodEnd: fact.periodEnd }, inputFactRefs: fact.factKind === 'comparison' ? facts.slice(0, 2).map(item => ({ analysisId, factId: item.factId })) : [], warnings: [] } })
    })
    await page.goto(process.env.REPORT_EDITOR_URL ?? 'http://127.0.0.1:4173/reports/v1/editor/fixture-report/1', { waitUntil: 'networkidle' })
    await page.locator('[data-marker-kind="analysis"]').click()
    await page.locator('.evidence-analysis-overview').waitFor()
    assert.equal(await page.locator('.evidence-fact-name').count(), 3)
    assert.ok((await page.locator('.evidence-analysis-overview').textContent()).includes('登记值 12,450 万元'))
    if (longName) {
      const toggle = page.getByRole('button', { name: '来源目录', exact: true })
      if (width < 1101) await toggle.click()
      const directory = page.locator('.evidence-directory')
      assert.equal(await directory.evaluate(node => node.scrollWidth <= node.clientWidth), true, '长名称与六位分析编号不撑宽目录')
      const names = await directory.locator('.evidence-directory-item:has(.evidence-directory-meta) .evidence-directory-label').allTextContents()
      assert.deepEqual(names, [name, name, name], '目录保留完整业务名称')
      assert.equal(await directory.locator('.evidence-directory-analysis').first().textContent(), '分析 123456')
      await page.screenshot({ path: new URL(`report-editor-facts-directory-${width}-long.png`, output).pathname })
      if (width < 1101) await toggle.click()
    }
    if (width === 1280) {
      const directorySearch = page.locator('.evidence-directory-search')
      for (const query of [analysisId, `分析 ${analysisId.replace('analysis_', '')}`]) {
        await directorySearch.fill(query)
        assert.equal(await page.locator('.evidence-directory-item:has(.evidence-directory-meta)').count(), 3, '按分析归属筛选事实')
      }
      await directorySearch.fill('analysis_002')
      assert.equal(await page.locator('.evidence-directory-item').count(), 0, '未登记的分析不匹配其他事实')
      await directorySearch.fill('')
    }
    const audit = async stage => {
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
      assert.equal(await page.locator('.evidence-workspace').evaluate(node => node.scrollWidth <= node.clientWidth), true)
      await page.screenshot({ path: new URL(`report-editor-facts-${stage}-${width}${longName ? '-long' : ''}.png`, output).pathname })
    }
    await audit('overview')
    await page.getByRole('searchbox', { name: '筛选分析事实' }).fill('fact-comparison')
    assert.equal(await page.locator('.evidence-analysis-overview li:visible').count(), 1)
    await page.locator('[data-fact-id="fact-comparison"]').click()
    await page.locator('.evidence-fact-metadata').waitFor()
    assert.equal(await page.locator('.evidence-object-title').textContent(), name)
    assert.equal(await page.locator('.evidence-fact-value').textContent(), '登记变化额 2,450 万元')
    assert.ok((await page.locator('.evidence-fact-metadata').textContent()).includes('变化率24.5%'))
    assert.ok((await page.locator('.evidence-fact-inputs').textContent()).includes('同比基期'))
    assert.equal((await page.locator('.evidence-fact-inputs').textContent()).includes('fact-baseline'), false)
    const collapse = page.getByRole('button', { name: '收起', exact: true })
    if (await collapse.isVisible()) await collapse.click()
    await audit('comparison')
    await page.locator('.evidence-fact-inputs button').first().click()
    await page.locator('.evidence-fact-value', { hasText: '登记值 12,450 万元' }).waitFor()
    assert.ok((await page.locator('.evidence-fact-metadata').textContent()).includes('统计范围院区：东院、西院'))
    const collapseMetric = page.getByRole('button', { name: '收起', exact: true })
    if (await collapseMetric.isVisible()) await collapseMetric.click()
    await audit('metric')
    assert.deepEqual(errors, [])
    await page.close()
  }
  console.log(JSON.stringify({ viewports: widths, longName, facts: 3, filtering: true, periods: true, comparison: true, namedInputs: true, errors: [] }))
} finally {
  await browser.close()
}
