import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { chromium, firefox, webkit } from 'playwright'

const engine = process.env.REPORT_EDITOR_BROWSER ?? 'chromium'
assert.ok(['chromium', 'firefox', 'webkit'].includes(engine), `Unsupported browser: ${engine}`)
const browser = await ({ chromium, firefox, webkit })[engine].launch({ headless: true })
try {
  for (const reducedMotion of ['reduce', 'no-preference']) {
    const page = await browser.newPage({ reducedMotion, viewport: { width: 1280, height: 900 } })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.addInitScript(() => {
      window.evidenceScrollCalls = []
      const original = Element.prototype.scrollIntoView
      Element.prototype.scrollIntoView = function (options) {
        if (this.closest('#report-editor')) window.evidenceScrollCalls.push({ options, text: this.textContent })
        return original.call(this, options)
      }
    })
    await page.goto(process.env.REPORT_EDITOR_URL ?? 'http://127.0.0.1:4173/reports/v1/editor/fixture-report/1', { waitUntil: 'networkidle' })
    await page.route('**/api/document', route => route.request().method() === 'PUT'
      ? route.fulfill({ status: 503, json: { detail: { code: 'fixture-save-unavailable' } } }) : route.continue())
    await page.locator('[data-action="sources"]').click()
    await page.locator('.evidence-directory-item', { hasText: '正文引用' }).click()
    await page.getByRole('button', { name: '定位正文', exact: true }).click()
    const target = page.locator('#report-editor .ProseMirror p', { hasText: '12,450' })
    await target.waitFor()
    await page.locator('#report-editor .report-located-subject').waitFor()
    assert.equal(await page.locator('#report-editor .ProseMirror').evaluate(node => node === document.activeElement), true)
    assert.equal(await page.locator('.evidence-shell').isVisible(), false)
    const call = await page.evaluate(() => window.evidenceScrollCalls.at(-1))
    assert.deepEqual(call.options, { block: 'center', behavior: reducedMotion === 'reduce' ? 'auto' : 'smooth' })
    assert.ok(call.text.includes('12,450'))
    if (reducedMotion === 'reduce') {
      const output = new URL('../../../../output/', import.meta.url)
      await mkdir(output, { recursive: true })
      const filename = engine === 'chromium' ? 'report-editor-v6-locate-highlight.png' : `report-editor-v6-${engine}-locate-highlight.png`
      await page.screenshot({ path: new URL(filename, output).pathname })
    }
    await page.keyboard.type('LOCATEEDIT')
    await page.locator('#report-editor .report-located-subject', { hasText: 'LOCATEEDIT' }).waitFor()
    await page.waitForFunction(() => !document.querySelector('#report-editor .report-located-subject'))
    assert.equal(await page.locator('#report-editor .ProseMirror').evaluate(node => node === document.activeElement), true)
    assert.ok((await target.textContent()).includes('LOCATEEDIT'))
    await page.keyboard.press('Control+z')
    assert.equal((await target.textContent()).includes('LOCATEEDIT'), false)
    assert.deepEqual(errors, [])
    await page.close()
  }
  console.log(JSON.stringify({ engine, citationScrollPreference: 'passed', reduce: 'auto', default: 'smooth', persistentFocus: 'passed', continuedEditing: 'passed', highlightCleanup: 'passed', undo: 'passed' }))
} finally {
  await browser.close()
}
