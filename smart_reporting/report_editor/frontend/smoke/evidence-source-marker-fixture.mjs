// 固定正文验证组合引用；不修改真实报告或fixture服务端正文。
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { chromium } from 'playwright'
const browser = await chromium.launch({ headless: true })
try {
  await mkdir('/home/junge/pros/smart_reporting/output', { recursive: true })
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } })
  const errors = []
  let writes = 0
  page.on('pageerror', error => errors.push(error.name))
  await page.route('**/api/document', async route => {
    if (route.request().method() !== 'GET') { writes++; return route.abort() }
    const response = await route.fetch()
    const payload = await response.json()
    payload.markdown = '# 报告\n\n## 月度收入[[analysis:analysis_001]] [[citation:sub-fixture-001]]\n\n收入保持稳定。[[citation:sub-fixture-001]]\n'
    await route.fulfill({ response, json: payload })
  })
  await page.goto(process.env.REPORT_EDITOR_URL ?? 'http://127.0.0.1:4173/reports/v1/editor/fixture-report/1', { waitUntil: 'networkidle' })
  const editor = page.locator('.ProseMirror')
  await editor.waitFor()
  const raw = await editor.textContent()
  const grouped = page.locator('.report-protocol-marker[data-marker-count="2"]')
  const single = page.locator('.report-protocol-marker[data-marker-count="1"]')
  assert.equal(await grouped.count(), 1)
  assert.equal(await single.count(), 1)
  assert.equal(await grouped.getAttribute('aria-haspopup'), 'dialog')
  const visual = await grouped.evaluate(element => ({
    count: getComputedStyle(element, '::before').content,
    icon: getComputedStyle(element, '::after').maskImage !== 'none',
    text: getComputedStyle(element, '::after').content,
  }))
  assert.deepEqual(visual, { count: '"2"', icon: true, text: '""' })
  await page.screenshot({ path: '/home/junge/pros/smart_reporting/output/report-editor-source-groups-body-390.png' })
  await grouped.click()
  const dialog = page.locator('.report-source-picker')
  await dialog.waitFor()
  await page.keyboard.press('Escape')
  await dialog.waitFor({ state: 'detached' })
  assert.equal(await grouped.evaluate(element => element === document.activeElement), true)
  await grouped.press('Space')
  await dialog.waitFor()
  await dialog.getByRole('button', { name: '关闭', exact: true }).click()
  await dialog.waitFor({ state: 'detached' })
  await grouped.press('Enter')
  await dialog.waitFor()
  await page.screenshot({ path: '/home/junge/pros/smart_reporting/output/report-editor-source-group-picker-390.png' })
  await dialog.getByRole('button', { name: '引用来源 2', exact: true }).click()
  await page.locator('.evidence-subject-links').waitFor()
  await page.getByRole('button', { name: '定位正文', exact: true }).click()
  await page.locator('h2.report-located-subject').waitFor({ timeout: 3000 })
  assert.equal(await editor.textContent(), raw)
  await grouped.click()
  await dialog.getByRole('button', { name: '引用来源 2', exact: true }).click()
  await page.locator('.evidence-subject-links').waitFor()
  await page.waitForTimeout(100)
  assert.equal(await page.evaluate(() => document.querySelector('.evidence-shell')?.contains(document.activeElement)), true)
  await page.getByRole('tab', { name: '报告正文', exact: true }).click()
  await single.focus()
  await single.press('Enter')
  await page.locator('.evidence-subject-links').waitFor()
  assert.equal(await dialog.count(), 0)
  assert.equal(writes, 0)
  assert.deepEqual(errors, [])
  await writeFile('/home/junge/pros/smart_reporting/output/report-editor-source-groups-result.json', JSON.stringify({ grouped: 'passed', single: 'passed', keyboard: 'passed', cancelFocus: 'passed', sourceFocus: 'passed', locateGrouped: 'passed', unchanged: true, writes, errors }, null, 2))
  console.log('source marker groups passed')
} finally { await browser.close() }
