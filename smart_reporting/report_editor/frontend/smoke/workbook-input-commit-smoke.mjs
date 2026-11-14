import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { join, resolve } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
import AxeBuilder from '@axe-core/playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const output = resolve(process.env.WORKBOOK_INPUT_COMMIT_OUTPUT ?? '/tmp/office-xlsx-input-commit-browser-20261112')
const port = Number(process.env.WORKBOOK_INPUT_COMMIT_PORT ?? 4290)
const base = `http://127.0.0.1:${port}/reports/v1/editor/assets/`
const modes = process.env.WORKBOOK_INPUT_COMMIT_MODE ? [process.env.WORKBOOK_INPUT_COMMIT_MODE] : ['zoom', 'consolidate', 'args', 'collapsed', 'external', 'catalog']
const views = [[1440, 900], [640, 360], [390, 320], [320, 640]]
const protections = ['composition', 'legacy', 'handled']
const html = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>工作表输入确认检查</title></head><body><script type="module" src="./smoke/workbook-input-commit-fixture.mjs"></script></body></html>'
const server = spawn('./node_modules/.bin/vite', ['--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'pipe' })
let log = '', browser
server.stdout.on('data', data => { log += data }); server.stderr.on('data', data => { log += data })
const evidence = { kind: 'real-product-components-with-callback-fixtures', cases: [], pageErrors: [], consoleErrors: [], httpErrors: [] }
async function protectedKey(field, key, protection) {
  return field.evaluate((node, { key, protection }) => {
    const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, isComposing: protection === 'composition', keyCode: protection === 'legacy' ? 229 : 0 })
    if (protection === 'handled') event.preventDefault()
    node.dispatchEvent(event)
    return { connected: node.isConnected, focused: node === document.activeElement, value: node.value }
  }, { key, protection })
}
try {
  await mkdir(output, { recursive: true })
  for (let attempt = 0; ; attempt++) {
    assert.equal(server.exitCode, null, log)
    try { if ((await fetch(base)).ok) break } catch {}
    assert(attempt < 120, log); await delay(250)
  }
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  for (const mode of modes) for (const [width, height] of views) {
    const label = `${mode}-${width}x${height}`
    const context = await browser.newContext({ viewport: { width, height } }), page = await context.newPage()
    page.on('pageerror', error => evidence.pageErrors.push({ label, message: error.message }))
    page.on('console', message => { if (message.type() === 'error') evidence.consoleErrors.push({ label, message: message.text() }) })
    page.on('response', response => { if (response.status() >= 400) evidence.httpErrors.push({ label, url: response.url(), status: response.status() }) })
    await page.route('**/workbook-input-commit-fixture.html?*', route => route.fulfill({ contentType: 'text/html', body: html }))
    await page.goto(`${base}workbook-input-commit-fixture.html?mode=${mode}`)
    await page.waitForSelector('html[data-fixture-ready=true]')
    const trigger = page.locator('#open-dialog'); await trigger.focus(); await page.keyboard.press('Enter')
    const dialog = page.getByRole('dialog')
    await dialog.waitFor(); await page.evaluate(() => document.fonts.ready)
    if (mode === 'collapsed') await dialog.locator('.fn-args-pick').click()
    const field = mode === 'zoom' ? dialog.getByRole('spinbutton', { name: '自定义缩放比例' })
      : mode === 'consolidate' ? dialog.getByRole('textbox', { name: '引用位置', exact: true })
      : mode === 'external' ? dialog.getByRole('textbox', { name: '外部区域：预算.xlsx' })
      : mode === 'catalog' ? dialog.getByRole('textbox').first() : dialog.locator('#fn-arg-0')
    const draft = mode === 'zoom' ? '138' : mode === 'consolidate' ? 'Source!A1:B3' : mode === 'external' ? 'B2:B4' : mode === 'catalog' ? 'SUM' : 'A2:A4'
    await field.fill(draft); await field.focus()
    const protectedChecks = []
    for (const key of mode === 'catalog' ? ['Escape'] : ['Enter', 'Escape']) for (const protection of protections) {
      const state = await protectedKey(field, key, protection)
      assert(state.connected && state.focused && state.value === draft, label + ' protected ' + key)
      assert.deepEqual(await page.evaluate(() => window.workbookInputFixture.stats()), { commits: [], cancels: 0 }, label)
      if (mode === 'consolidate') assert.equal(await dialog.locator('[data-reference]').count(), 0, label)
      if (mode === 'external') assert.equal(await dialog.locator('#fn-arg-0').inputValue(), 'A1:A3', label)
      if (mode === 'collapsed') assert.equal(await dialog.locator('.fn-args-pick').getAttribute('aria-expanded'), 'false', label)
      protectedChecks.push({ key, protection, ...state })
    }
    // 真实按键先由子字段消费，产品父层须尊重 defaultPrevented。
    await field.evaluate(node => { node.addEventListener('keydown', event => { if (event.key === 'Enter' && event.isTrusted) event.preventDefault() }, { capture: true, once: true }) })
    await field.press('Enter')
    assert.equal(await field.inputValue(), draft, label + ' consumed trusted Enter')
    assert.deepEqual(await page.evaluate(() => window.workbookInputFixture.stats()), { commits: [], cancels: 0 }, label)
    if (['args', 'collapsed', 'external', 'catalog'].includes(mode)) {
      const outside = page.locator('#worksheet'); await outside.focus()
      for (const protection of protections) {
        await protectedKey(outside, 'Escape', protection)
        assert.deepEqual(await page.evaluate(() => window.workbookInputFixture.stats()), { commits: [], cancels: 0 }, label + ' outside Escape')
      }
      await field.focus()
    }
    for (const key of ['Tab', 'Shift+Tab']) for (let i = 0; i < 10; i++) {
      await page.keyboard.press(key)
      assert(await dialog.evaluate(node => node.contains(document.activeElement)), label + ' focus escaped: ' + key)
    }
    await field.focus(); await field.scrollIntoViewIfNeeded()
    const hit = await field.evaluate(node => { const r = node.getBoundingClientRect(); return { visible: r.top >= 0 && r.bottom <= innerHeight && r.left >= 0 && r.right <= innerWidth, hit: node.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)) } })
    assert(hit.visible && hit.hit, label + ' field outside viewport or covered')
    let externalLayout
    if (mode === 'external') {
      externalLayout = await dialog.locator('.fn-args-external .input-row').evaluate(node => {
        const button = node.querySelector('button'), select = node.querySelector('select'), range = document.createRange()
        range.selectNodeContents(button)
        const style = getComputedStyle(select), canvas = document.createElement('canvas'), measure = canvas.getContext('2d')
        measure.font = style.font
        const needed = measure.measureText(select.selectedOptions[0].text).width + parseFloat(style.paddingLeft) + parseFloat(style.paddingRight) + 24
        return { buttonTextLines: range.getClientRects().length, selectWidth: select.getBoundingClientRect().width, needed, horizontalOverflow: node.scrollWidth > node.clientWidth }
      })
      assert.equal(externalLayout.buttonTextLines, 1, label + ' external insert label wraps')
      assert(externalLayout.selectWidth >= externalLayout.needed, label + ' external sheet name clipped')
      assert.equal(externalLayout.horizontalOverflow, false, label + ' external row overflows')
    }
    const axe = await new AxeBuilder({ page }).include('[role=dialog]').analyze()
    assert.deepEqual(axe.violations, [], label + ' axe')
    await page.screenshot({ path: join(output, label + '.png') })
    if (mode === 'catalog') {
      await page.locator('#worksheet').focus(); await page.keyboard.press('Escape')
      assert.deepEqual(await page.evaluate(() => window.workbookInputFixture.stats()), { commits: [], cancels: 1 }, label)
    } else {
      await field.press('Enter')
      if (mode === 'consolidate') {
        assert.equal(await field.inputValue(), '', label)
        assert.equal(await dialog.locator('[data-reference]').count(), 1, label)
        assert.deepEqual(await page.evaluate(() => window.workbookInputFixture.stats()), { commits: [], cancels: 0 }, label)
        await dialog.getByRole('button', { name: '确定', exact: true }).click()
      }
      if (mode === 'collapsed') {
        assert.equal(await dialog.locator('.fn-args-pick').getAttribute('aria-expanded'), 'true', label)
        assert.deepEqual(await page.evaluate(() => window.workbookInputFixture.stats()), { commits: [], cancels: 0 }, label)
        await dialog.locator('#fn-arg-0').press('Enter')
      }
      if (mode === 'external') {
        assert.equal(await dialog.locator('#fn-arg-0').inputValue(), "'[1]数据表'!B2:B4", label)
        assert.deepEqual(await page.evaluate(() => window.workbookInputFixture.stats()), { commits: [], cancels: 0 }, label)
        assert(await dialog.locator('#fn-arg-0').evaluate(node => node === document.activeElement), label)
        await dialog.locator('#fn-arg-0').press('Enter')
      }
      const expected = mode === 'zoom' ? 'zoom:138' : mode === 'consolidate' ? { fn: 'sum', leftLabels: false, references: ['Source!A1:B3'] } : mode === 'external' ? ["'[1]数据表'!B2:B4"] : ['A2:A4']
      assert.deepEqual(await page.evaluate(() => window.workbookInputFixture.stats()), { commits: [expected], cancels: 0 }, label)
    }
    await dialog.waitFor({ state: 'hidden' })
    assert(await trigger.evaluate(node => node === document.activeElement), label + ' opener not restored')
    evidence.cases.push({ label, mode, width, height, protectedChecks, trustedConsumedEnter: true, tabChecks: 20, hit, externalLayout, axeViolations: axe.violations, stats: await page.evaluate(() => window.workbookInputFixture.stats()), openerRestored: true })
    await writeFile(join(output, 'evidence.json'), JSON.stringify(evidence, null, 2)); console.log(label + ' passed')
    await context.close()
  }
  for (const key of ['pageErrors', 'consoleErrors', 'httpErrors']) assert.deepEqual(evidence[key], [])
  evidence.ok = true; evidence.browserVersion = browser.version()
  await writeFile(join(output, 'evidence.json'), JSON.stringify(evidence, null, 2))
  console.log(JSON.stringify({ ok: true, cases: evidence.cases.length, output }))
} catch (error) {
  await writeFile(join(output, 'failure.json'), JSON.stringify({ error: String(error), stack: error.stack, log, evidence }, null, 2)); throw error
} finally { await browser?.close(); server.kill('SIGTERM') }
