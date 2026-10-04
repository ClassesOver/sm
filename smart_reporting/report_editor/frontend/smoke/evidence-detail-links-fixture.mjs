import assert from 'node:assert/strict'
import { chromium } from 'playwright'

const browser = await chromium.launch({ headless: true })
try {
  const cases = (process.env.REPORT_EDITOR_LINK_CASES ?? 'subject-fact,subject-computation,input,output').split(',')
  assert.ok(cases.every(value => ['subject-fact', 'subject-computation', 'input', 'output'].includes(value)))
  for (const scenario of cases) {
    const kind = scenario === 'subject-computation' ? '计算' : '事实'
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.goto(process.env.REPORT_EDITOR_URL ?? 'http://127.0.0.1:4173/reports/v1/editor/fixture-report/1', { waitUntil: 'networkidle' })
    if (scenario === 'input') {
      await page.route('**/api/facts/analysis-fixture-001/*', async route => {
        const leaf = route.request().url().endsWith('/fact-input-fixture')
        await route.fulfill({ json: {
          analysisId: 'analysis-fixture-001', factId: leaf ? 'fact-input-fixture' : 'fact-fixture-001',
          factKind: 'metric', displayValue: 12450, entry: { unit: '万元' }, warnings: [],
          inputFactRefs: leaf ? [] : [{ analysisId: 'analysis-fixture-001', factId: 'fact-input-fixture' }],
        } })
      })
    }
    await page.locator('[data-action="sources"]').click()
    await page.locator('.evidence-directory-item', { hasText: '正文引用' }).click()
    if (scenario === 'input' || scenario === 'output') {
      await page.locator('.evidence-subject-links button', { hasText: scenario === 'input' ? '事实' : '计算' }).click()
    }
    const selector = scenario === 'input' ? '.evidence-fact-inputs button'
      : scenario === 'output' ? '.evidence-computation-outputs button' : '.evidence-subject-links button'
    const link = scenario.startsWith('subject') ? page.locator(selector, { hasText: kind }) : page.locator(selector)
    await link.waitFor()
    const title = await page.locator('.evidence-object-title').textContent()
    const hadHistory = await page.locator('[data-evidence="back"]').isEnabled()
    const targetTitle = scenario === 'input' ? 'fact-input-fixture'
      : kind === '计算' ? '渠道收入汇总' : 'fact-fixture-001'
    await link.click({ modifiers: ['Control'] })
    assert.equal(await page.locator('.evidence-tab-name').count(), 2)
    assert.equal(await page.locator('.evidence-object-title').textContent(), title)
    assert.equal(await page.locator('[data-evidence="back"]').isEnabled(), hadHistory)
    await link.click({ button: 'middle' })
    assert.equal(await page.locator('.evidence-tab-name').count(), 2)
    assert.equal(await page.locator('.evidence-object-title').textContent(), title)
    await link.click({ modifiers: ['Control', 'Shift'] })
    await page.locator('.evidence-object-title', { hasText: targetTitle }).waitFor()
    assert.equal(await page.locator('.evidence-tab-name').count(), 2)
    assert.equal(await page.locator('.evidence-tab[aria-selected="true"] .evidence-tab-stage').textContent(), kind)
    await page.locator('.evidence-tab', { hasText: '正文引用' }).click()
    await link.waitFor()
    await link.click()
    await page.locator('.evidence-object-title', { hasText: targetTitle }).waitFor()
    assert.equal(await page.locator('[data-evidence="back"]').isEnabled(), true)
    assert.equal(await page.locator('.evidence-tab-name').count(), 2)
    await page.locator('[data-evidence="back"]').click()
    await page.locator('.evidence-object-title').filter({ hasText: title }).waitFor()
    assert.deepEqual(errors, [])
    await page.close()
  }
  console.log(JSON.stringify({ detailLinks: cases, background: 'passed', foreground: 'passed', deduplication: 'passed', plainNavigation: 'passed', back: 'passed' }))
} finally {
  await browser.close()
}
