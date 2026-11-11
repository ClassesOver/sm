import { chromium } from 'playwright'
import assert from 'node:assert/strict'

const base = process.env.SMART_REPORTING_URL ?? 'http://127.0.0.1:5173'
const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage()
  await page.goto(base, { waitUntil: 'domcontentloaded' })
  await page.evaluate(async () => {
    const { createNativeChartEditDialog } = await import('/reports/v1/editor/assets/src/slides-native-chart-edit.ts')
    const trigger = document.createElement('button'); trigger.textContent = 'Open chart editor'; document.body.append(trigger)
    trigger.addEventListener('click', () => createNativeChartEditDialog(document.body, {
      mode: 'type', initial: { kind: 'bar', categories: ['A'], series: [{ name: 'S', values: [1] }] }, onConfirm: () => {}, onClose: () => {},
    }))
    trigger.click()
  })
  const dialog = page.locator('.slides-native-chart-dialog[role="dialog"]')
  await dialog.waitFor({ state: 'visible', timeout: 15000 })
  assert.equal(await dialog.locator('[data-chart-kind]').count(), 13)
  await dialog.locator('[data-chart-kind="line"]').click()
  await dialog.locator('[data-chart-confirm]').click()
  await dialog.waitFor({ state: 'detached' })
  console.log('PASS native chart type dialog exposes the fixed 13-kind gallery and confirms')
} finally { await browser.close() }
