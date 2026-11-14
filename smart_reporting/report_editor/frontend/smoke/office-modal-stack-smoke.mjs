import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { join, resolve } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
import AxeBuilder from '@axe-core/playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const output = resolve(process.env.OFFICE_MODAL_STACK_OUTPUT ?? '/tmp/office-modal-stack-browser-20261112')
const port = Number(process.env.OFFICE_MODAL_STACK_PORT ?? 4288)
const base = `http://127.0.0.1:${port}/reports/v1/editor/assets/`
const modes = ['xlsx', 'docx', 'nested', 'busy', 'remove-parent', 'pptx', 'pdf']
const views = [[1440, 900], [640, 360], [390, 320], [320, 640]]
const html = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Office 弹窗层级检查</title></head><body><script type="module" src="./smoke/office-modal-stack-fixture.mjs"></script></body></html>'
const server = spawn('./node_modules/.bin/vite', ['--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'pipe' })
let log = '', browser
server.stdout.on('data', data => { log += data }); server.stderr.on('data', data => { log += data })
const evidence = { kind: 'real-product-dialog-components-with-callback-fixtures', cases: [], pageErrors: [], consoleErrors: [], httpErrors: [] }
try {
  await mkdir(output, { recursive: true })
  for (let attempt = 0; ; attempt++) {
    assert.equal(server.exitCode, null, log)
    try { if ((await fetch(base)).ok) break } catch {}
    assert(attempt < 120, log); await delay(250)
  }
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  for (const mode of modes) for (const [width, height] of views) {
    const label = `${mode}-${width}x${height}`, native = mode === 'pptx' || mode === 'pdf'
    const context = await browser.newContext({ viewport: { width, height } }), page = await context.newPage()
    page.on('pageerror', error => evidence.pageErrors.push({ label, message: error.message }))
    page.on('console', message => { if (message.type() === 'error') evidence.consoleErrors.push({ label, message: message.text() }) })
    page.on('response', response => { if (response.status() >= 400) evidence.httpErrors.push({ label, url: response.url(), status: response.status() }) })
    await page.route('**/office-modal-stack-fixture.html?*', route => route.fulfill({ contentType: 'text/html', body: html }))
    await page.goto(`${base}office-modal-stack-fixture.html?mode=${mode}`)
    await page.waitForSelector('html[data-fixture-ready=true]')
    const trigger = page.locator('#stack-trigger')
    await trigger.focus(); await page.keyboard.press('Enter')
    const parent = page.locator('[role=dialog][aria-label="编辑设置"]')
    const parentDraft = parent.getByRole('textbox', { name: '当前草稿' }), original = await parentDraft.inputValue()
    const opener = parent.locator('[data-open-child]')
    await opener.focus(); await page.keyboard.press('Enter')
    const childName = mode === 'xlsx' ? '缩放' : mode === 'docx' ? '标题/说明' : mode === 'pptx' ? '自定义幻灯片尺寸' : mode === 'pdf' ? '提取页面' : '高级设置'
    const child = page.getByRole('dialog', { name: childName, exact: true })
    await child.waitFor(); await page.evaluate(() => document.fonts.ready); await page.waitForTimeout(300)
    const field = mode === 'xlsx' ? child.getByRole('spinbutton', { name: '自定义缩放比例' }) : mode === 'pptx' ? child.getByRole('textbox', { name: '幻灯片宽度' }) : mode === 'pdf' ? child.getByRole('textbox', { name: '提取页码' }) : child.getByRole('textbox').first()
    const draft = mode === 'xlsx' ? '137' : mode === 'pptx' ? '26.5' : mode === 'pdf' ? '1,3' : '子窗口的中文草稿尚未提交'
    await field.fill(draft)
    const access = await page.evaluate(() => ({ parentInert: window.modalStackFixture.parent.overlay.inert, parentModal: window.modalStackFixture.parent.overlay.getAttribute('aria-modal') }))
    assert.equal(access.parentModal, native ? 'true' : 'false', label)
    assert.equal(access.parentInert, !native && mode !== 'nested', label)
    const ime = []
    for (const protection of ['composition', 'legacy', 'handled']) {
      const result = await field.evaluate((node, protection) => {
        const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true, isComposing: protection === 'composition', keyCode: protection === 'legacy' ? 229 : 0 })
        if (protection === 'handled') event.preventDefault()
        node.dispatchEvent(event)
        return { protection, connected: node.isConnected, focused: node === document.activeElement, value: node.value }
      }, protection)
      assert(result.connected && result.focused && result.value === draft, label + ' protected Escape')
      assert.equal(await parent.getAttribute('hidden'), null, label); ime.push(result)
    }
    for (const key of ['Tab', 'Shift+Tab']) for (let i = 0; i < 12; i++) {
      await page.keyboard.press(key)
      const focus = await child.evaluate(node => ({ inside: node.contains(document.activeElement), active: document.activeElement?.outerHTML.slice(0, 250) }))
      if (!focus.inside) await page.screenshot({ path: join(output, label + '-focus-failure.png') })
      assert(focus.inside, label + ': ' + key + ' focus escaped: ' + JSON.stringify({ step: i, ...focus }))
    }
    await field.focus(); await field.scrollIntoViewIfNeeded()
    const hit = await field.evaluate(node => { const r = node.getBoundingClientRect(); return { visible: r.top >= 0 && r.bottom <= innerHeight && r.left >= 0 && r.right <= innerWidth, hit: node.contains(document.elementFromPoint(r.x+r.width/2, r.y+r.height/2)) } })
    assert(hit.visible && hit.hit, label + ' child hidden behind parent or outside viewport')
    const axe = await new AxeBuilder({ page }).include(native ? 'dialog[open]' : `.modal-overlay[aria-label="${childName}"]`).analyze()
    assert.deepEqual(axe.violations, [], label + ' axe')
    await page.screenshot({ path: join(output, label + '.png') })
    let pendingAxe
    if (mode === 'pdf') {
      await child.getByRole('button', { name: '生成独立 PDF', exact: true }).click()
      assert(await field.isDisabled(), label + ' pending field not locked')
      for (const key of ['Tab', 'Shift+Tab']) for (let i = 0; i < 6; i++) {
        await page.keyboard.press(key)
        assert(await child.evaluate(node => node.contains(document.activeElement)), label + ' pending focus escaped')
      }
      const reading = child.getByRole('region', { name: '提取说明与进度', exact: true })
      await reading.focus(); await reading.press('End')
      const readingState = await reading.evaluate(node => ({ focused: node === document.activeElement, ring: parseFloat(getComputedStyle(node).outlineWidth), scrollable: node.scrollHeight > node.clientHeight, scrollTop: node.scrollTop }))
      assert(readingState.focused && readingState.ring >= 2, label + ' pending reading focus')
      if (readingState.scrollable) { await page.waitForTimeout(200); assert(await reading.evaluate(node => node.scrollTop > 0), label + ' keyboard cannot scroll pending description') }
      await reading.press('Home')
      pendingAxe = await new AxeBuilder({ page }).include('dialog[open]').analyze()
      assert.deepEqual(pendingAxe.violations, [], label + ' pending axe')
      await page.screenshot({ path: join(output, label + '-pending.png') })
    }
    if (mode === 'busy') {
      await page.keyboard.press('Escape')
      assert.equal(await child.count(), 1); assert(await child.isVisible(), label)
      assert.equal((await page.evaluate(() => window.modalStackFixture.stats())).requests, 1)
      assert.equal(await parent.getAttribute('hidden'), null, label)
      await page.evaluate(() => window.modalStackFixture.release())
    }
    if (mode === 'remove-parent') {
      await page.evaluate(() => window.modalStackFixture.removeParent())
      assert.equal(await page.evaluate(() => window.modalStackFixture.parent.card.querySelector('input').value), original, label)
    }
    await page.keyboard.press('Escape'); await child.waitFor({ state: 'hidden' })
    if (mode !== 'remove-parent') {
      assert.equal(await parent.getAttribute('hidden'), null, label)
      assert.equal(await parentDraft.inputValue(), original, label)
      assert(await opener.evaluate(node => node === document.activeElement), label + ' child opener not restored')
      if (mode === 'xlsx') await page.evaluate(() => { window.modalStackFixture.reopenParent(); window.modalStackFixture.reopenParent() })
      await page.keyboard.press('Escape'); await parent.waitFor({ state: 'hidden' })
    }
    assert(await trigger.evaluate(node => node === document.activeElement), label + ' document opener not restored')
    const stats = await page.evaluate(() => window.modalStackFixture.stats())
    assert.equal(stats.commits, mode === 'pdf' ? 1 : 0, label)
    assert.equal(stats.ancestorRequests, 0, label + ' Escape reached ancestor handler')
    evidence.cases.push({ label, mode, width, height, native, access, ime, tabChecks: 24, hit, axeViolations: axe.violations, pendingAxeViolations: pendingAxe?.violations, pendingReadingChecked: mode === 'pdf', stats, openerRestored: true, parentDraftUnchanged: true })
    await writeFile(join(output, 'evidence.json'), JSON.stringify(evidence, null, 2))
    console.log(label + ' passed'); await context.close()
  }
  for (const key of ['pageErrors', 'consoleErrors', 'httpErrors']) assert.deepEqual(evidence[key], [])
  evidence.ok = true; evidence.browserVersion = browser.version()
  await writeFile(join(output, 'evidence.json'), JSON.stringify(evidence, null, 2))
  console.log(JSON.stringify({ ok: true, cases: evidence.cases.length, output }))
} catch (error) {
  await writeFile(join(output, 'failure.json'), JSON.stringify({ error: String(error), stack: error.stack, log, evidence }, null, 2)); throw error
} finally { await browser?.close(); server.kill('SIGTERM') }
