import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { join, resolve } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
import AxeBuilder from '@axe-core/playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url)), output = resolve(process.env.WORKBOOK_TOOL_STATE_OUTPUT ?? '/dev/shm/office-xlsx-tool-state-browser-20261112')
const port = Number(process.env.WORKBOOK_TOOL_STATE_PORT ?? 4292), base = `http://127.0.0.1:${port}/reports/v1/editor/assets/`
const html = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>工作表工具状态检查</title></head><body><script type="module" src="./smoke/workbook-tool-state-fixture.mjs"></script></body></html>'
const server = spawn('./node_modules/.bin/vite', ['--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'pipe' })
let browser, currentPage, log = ''
server.stdout.on('data', data => { log += data }); server.stderr.on('data', data => { log += data })
const evidence = { kind: 'real-product-watch-and-pivot-adapter-with-explicit-workbook-viewport-fixtures', cases: [], pageErrors: [], consoleErrors: [], httpErrors: [] }
const protections = ['composition', 'legacy', 'handled']
async function protect(node, key, protection) {
  await node.evaluate((node, { key, protection }) => {
    const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, isComposing: protection === 'composition', keyCode: protection === 'legacy' ? 229 : 0 })
    if (protection === 'handled') event.preventDefault()
    node.dispatchEvent(event)
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
  for (const mode of ['empty', 'populated', 'unavailable', 'pivot']) for (const [width, height] of [[1440, 900], [640, 360], [390, 320], [320, 640]]) {
    const label = `${mode}-${width}x${height}`, context = await browser.newContext({ viewport: { width, height } }), page = await context.newPage()
    currentPage = page
    page.on('pageerror', error => evidence.pageErrors.push({ label, message: error.message }))
    page.on('console', message => { if (message.type() === 'error') evidence.consoleErrors.push({ label, message: message.text() }) })
    page.on('response', response => { if (response.status() >= 400) evidence.httpErrors.push({ label, status: response.status(), url: response.url() }) })
    await page.route('**/workbook-tool-state-fixture.html?*', route => route.fulfill({ contentType: 'text/html', body: html }))
    await page.goto(`${base}workbook-tool-state-fixture.html?mode=${mode}`); await page.waitForSelector('html[data-fixture-ready=true]')
    const opener = page.locator('#tool-open'); await opener.focus(); await page.keyboard.press('Enter'); await page.evaluate(() => document.fonts.ready)
    const stats = () => page.evaluate(() => window.workbookToolFixture.stats())
    const detail = { label, mode, width, height }
    if (mode === 'pivot') {
      const drag = page.locator('#pivot-drag'), box = await drag.boundingBox(), x = box.x + box.width / 2, y = box.y + box.height / 2
      await page.mouse.move(x, y); await page.mouse.down(); await page.mouse.move(x + 55, y + 25)
      assert((await stats()).preview, label)
      for (const protection of protections) { await protect(drag, 'Escape', protection); assert((await stats()).preview, label + ' protected drag'); assert.equal((await stats()).commits.length, 0, label) }
      await page.evaluate(() => window.workbookToolFixture.consumeNextEscape()); await page.keyboard.press('Escape'); assert((await stats()).preview, label + ' consumed actual Escape')
      await page.mouse.up(); assert.deepEqual((await stats()).commits, [{ row: 1, column: 1, width: 140, height: 110 }], label); assert.equal((await stats()).preview, false, label)
      await page.mouse.move(x, y); await page.mouse.down(); await page.mouse.move(x + 40, y + 30); assert((await stats()).preview, label)
      await page.keyboard.press('Escape'); assert.equal((await stats()).preview, false, label); await page.mouse.up(); assert.equal((await stats()).commits.length, 1, label)
      detail.pointerCommitThenCancel = true; detail.protectedEscape = 4
      await page.screenshot({ path: join(output, label + '.png') })
    } else {
      const panel = page.getByRole('dialog', { name: '监视窗口', exact: true }), scroll = panel.getByRole('region', { name: '监视单元格表格' })
      await panel.waitFor()
      if (mode === 'unavailable') await page.waitForFunction(() => document.querySelectorAll('.watch-gone').length === 12)
      assert.equal(await panel.locator('[data-watch-row]').count(), mode === 'empty' ? 0 : 12, label)
      if (mode === 'empty') assert(await panel.locator('[data-watch-add]').isDisabled(), label)
      await scroll.focus(); await scroll.evaluate(node => { node.scrollTop = 40 })
      const before = await scroll.evaluate(node => node.scrollTop)
      for (const key of ['Escape', 'Home', 'End']) for (const protection of protections) {
        await protect(scroll, key, protection)
        assert(await panel.isVisible(), label); assert.equal(await scroll.evaluate(node => node.scrollTop), before, label)
        assert(await scroll.evaluate(node => node === document.activeElement), label)
      }
      await scroll.evaluate(node => node.addEventListener('keydown', event => { if (event.key === 'Escape') event.preventDefault() }, { capture: true, once: true }))
      await page.keyboard.press('Escape'); assert(await panel.isVisible(), label + ' consumed actual Escape')
      const geometry = await panel.evaluate(node => { const r = node.getBoundingClientRect(); return { visible: r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= innerHeight, overflow: node.scrollWidth > node.clientWidth } })
      assert(geometry.visible && !geometry.overflow, label)
      for (const control of await panel.locator('button:enabled,.watch-scroll').all()) {
        await control.focus(); await page.keyboard.press('Tab'); await page.keyboard.press('Shift+Tab')
        const state = await control.evaluate(node => { const r = node.getBoundingClientRect(), s = getComputedStyle(node), hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2); return { label: node.getAttribute('aria-label') || node.textContent, focused: node === document.activeElement, hit: node.contains(hit), target: hit?.outerHTML.slice(0, 180), rect: r.toJSON(), outline: s.outlineWidth, outlineStyle: s.outlineStyle } })
        assert(state.focused && state.hit && parseFloat(state.outline) >= 2, label + ' control focus/hit/ring: ' + JSON.stringify(state))
      }
      await scroll.focus(); await page.keyboard.press('End')
      assert(await scroll.evaluate(node => node.scrollTop + node.clientHeight >= node.scrollHeight - 2), label + ' End')
      await page.keyboard.press('Home'); assert.equal(await scroll.evaluate(node => node.scrollTop), 0, label + ' Home')
      if (mode === 'unavailable') {
        const first = panel.locator('[data-watch-row]').first(), remove = first.locator('button')
        assert.equal(await first.locator('td').first().innerText(), '来源不可用', label)
        assert.equal(await first.locator('td').first().evaluate(node => getComputedStyle(node).textDecorationLine), 'none', label)
        assert.match(await first.locator('td').nth(1).evaluate(node => getComputedStyle(node).textDecorationLine), /line-through/, label)
        await remove.focus(); const handle = await first.elementHandle()
        await page.screenshot({ path: join(output, label + '-unavailable.png') })
        await scroll.focus(); await scroll.evaluate(node => { node.scrollLeft = 0; node.scrollTop = 0 })
        await page.screenshot({ path: join(output, label + '-unavailable-status.png') })
        await remove.focus()
        await page.evaluate(() => window.workbookToolFixture.restore()); await page.waitForFunction(() => document.querySelectorAll('.watch-gone').length === 0)
        assert(await remove.evaluate(node => node === document.activeElement), label + ' recovery focus')
        assert(await first.evaluate((node, original) => node === original, handle), label + ' recovery replaced row')
        assert.equal(await first.locator('td').first().innerText(), '跨年度部门汇总与费用分析', label)
        detail.recoveryPreservesRowAndFocus = true
      }
      const axe = await new AxeBuilder({ page }).include('[data-watch-window]').analyze(); assert.deepEqual(axe.violations, [], label + ' axe')
      detail.axeViolations = axe.violations; detail.geometry = geometry; detail.protectedKeys = 9
      await page.screenshot({ path: join(output, label + '.png') })
      // 非模态工具允许Tab返回工作表；关闭时回原入口，销毁后轮询停止。
      await panel.locator('[data-watch-close]').focus(); await page.keyboard.press('Escape'); await panel.waitFor({ state: 'detached' })
      assert(await opener.evaluate(node => node === document.activeElement), label + ' opener')
      const reads = (await stats()).reads; await page.waitForTimeout(900); assert.equal((await stats()).reads, reads, label + ' polling after close')
    }
    detail.stats = await stats(); assert.deepEqual(detail.stats.errors, [], label)
    evidence.cases.push(detail); await writeFile(join(output, 'evidence.json'), JSON.stringify(evidence, null, 2)); console.log(label + ' passed'); await context.close()
  }
  for (const key of ['pageErrors', 'consoleErrors', 'httpErrors']) assert.deepEqual(evidence[key], [])
  evidence.ok = true; evidence.browserVersion = browser.version(); await writeFile(join(output, 'evidence.json'), JSON.stringify(evidence, null, 2)); console.log(JSON.stringify({ ok: true, cases: evidence.cases.length, output }))
} catch (error) {
  await currentPage?.screenshot({ path: join(output, 'failure.png') }).catch(() => {})
  await writeFile(join(output, 'failure.json'), JSON.stringify({ error: String(error), stack: error.stack, log, evidence }, null, 2)); throw error
} finally { await browser?.close(); server.kill('SIGTERM') }
