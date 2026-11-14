// 固定源 PrintDialog：真实HTTP、页面设置草稿、系统打印HTML/PDF与独立保存回读。
import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { copyFile, mkdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
import { probeCanvasTextRendering } from './canvas-font-preflight.mjs'

const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const directory = process.env.WORKBOOK_PRINT_DIALOG_DIRECTORY ?? '/dev/shm/office-workbook-print-dialog-20261113/browser'
const resumeDirectory = process.env.WORKBOOK_PRINT_DIALOG_RESUME_FROM
const staticDirectory = process.env.PDF_SMOKE_STATIC_DIRECTORY, engineDirectory = process.env.AGENT_REPORTING_WORKBOOK_ENGINE_DIR
assert(staticDirectory && engineDirectory, '必须指定冻结前端与bridge')
const port = Number(process.env.WORKBOOK_PRINT_DIALOG_PORT ?? 4421), origin = `http://127.0.0.1:${port}`
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
await mkdir(directory, { recursive: false })
const manifest = await readFile(join(staticDirectory, '.vite/manifest.json')), engine = await readFile(join(engineDirectory, 'dist/cli.mjs'))
const backendPaths = ['smart_reporting/reporting/delivery/office_engine.py', ...['native_office.py', 'native.py', 'native_api.py'].map(name => `smart_reporting/report_editor/${name}`)]
const backend = Object.fromEntries(await Promise.all(backendPaths.map(async path => [path, sha(await readFile(join(repo, path)))])))
const nativeOfficeSha256 = backend['smart_reporting/report_editor/native_office.py']
await writeFile(join(directory, 'backend-start-identities.json'), JSON.stringify(backend, null, 2))
const python = args => spawnSync(join(repo, '.venv/bin/python'), [join(frontend, 'smoke/workbook-print-dialog-verify.py'), directory, ...args], { cwd: repo, encoding: 'utf8' })
let fixtureIdentity, resumedDrafts
if (resumeDirectory) {
  for (const file of ['fixture.xlsx', 'selected-pages.html', 'selected-pages.pdf']) await copyFile(join(resumeDirectory, file), join(directory, file))
  resumedDrafts = JSON.parse(await readFile(join(resumeDirectory, 'failure.json'), 'utf8')).diagnostics.drafts
  assert.equal(resumedDrafts.length, 1)
  fixtureIdentity = { sourceSha256: sha(await readFile(join(directory, 'fixture.xlsx'))) }
} else {
  const fixture = python(['--fixture']); assert.equal(fixture.status, 0, fixture.stderr)
  fixtureIdentity = JSON.parse(fixture.stdout)
}
const server = spawn(join(repo, '.venv/bin/python'), [join(frontend, 'smoke/workbook-ai-charts-server.py'), '--directory', directory, '--port', String(port), '--source', join(directory, 'fixture.xlsx')], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, stdio: 'pipe' })
let serverLog = '', browser, page, stage = 'server'
server.stdout.on('data', bytes => { serverLog += bytes }); server.stderr.on('data', bytes => { serverLog += bytes })
const errors = [], consoleErrors = [], httpErrors = [], assetErrors = [], assets = new Map(), checks = []
try {
  for (let i = 0; ; i++) {
    assert.equal(server.exitCode, null, serverLog)
    try { if ((await fetch(origin + '/__smoke__/state', { signal: AbortSignal.timeout(1500) })).ok) break } catch {}
    assert(i < 240, serverLog); await delay(250)
  }
  const info = JSON.parse(await readFile(join(directory, 'server-info.json'), 'utf8')); assert.equal(info.sourceSha256, fixtureIdentity.sourceSha256)
  browser = await chromium.launch({ headless: true })
  const preflight = await probeCanvasTextRendering(browser); assert.equal(preflight.ok, true, JSON.stringify(preflight))
  page = await browser.newPage({ viewport: { width: 1760, height: 1100 }, acceptDownloads: true })
  const cdp = await page.context().newCDPSession(page); await cdp.send('Network.enable'); await cdp.send('Network.setCacheDisabled', { cacheDisabled: true })
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  page.on('dialog', dialog => dialog.type() === 'beforeunload' ? dialog.accept() : dialog.dismiss())
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (response.status() >= 400) httpErrors.push({ path, status: response.status() })
    if (path.startsWith('/reports/v1/editor/assets/') && /\.(js|css)$/.test(path)) checks.push((async () => {
      assert.equal(response.status(), 200)
      const bytes = await response.body(), disk = await readFile(join(staticDirectory, path.slice('/reports/v1/editor/assets/'.length)))
      assert.equal(sha(bytes), sha(disk)); assets.set(path, sha(bytes))
    })().catch(error => assetErrors.push({ path, error: String(error) })))
  })
  // 只在实际浏览器spool边界截获HTML；不替换应用模块、journal、writer或HTTP。
  await page.addInitScript(() => {
    const append = Element.prototype.append
    Element.prototype.append = function (...nodes) {
      append.apply(this, nodes)
      for (const node of nodes) if (node instanceof HTMLIFrameElement && node.contentWindow) node.contentWindow.print = () => { window.__printDialogHtml = node.contentDocument.documentElement.outerHTML }
    }
  })
  if (resumedDrafts) await page.addInitScript(entries => { if (window.top !== window) return; for (const [key, value] of entries) localStorage.setItem(key, value) }, resumedDrafts)
  const ready = () => page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 60000 })
  const draft = () => page.evaluate(() => Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')).flatMap(([, value]) => JSON.parse(value).operations ?? []))
  const command = async (tab, id) => { await page.locator(`[data-ribbon-tab="${tab}"]`).click(); await page.locator(`[data-ribbon-command="${id}"]`).click() }
  const dialog = () => page.getByRole('dialog', { name: '打印预览', exact: true })
  const previewReady = () => page.waitForFunction(() => document.querySelector('[data-print-preview]')?.srcdoc.includes('class="page"') && !document.querySelector('[data-print-submit]')?.disabled, null, { timeout: 60000 })
  const openPrint = async () => { await command('File', 'print'); await dialog().waitFor(); await previewReady() }
  const select = async (name, value) => { await dialog().locator(`[data-print-${name}]`).selectOption(value); await previewReady(); assert.equal(await dialog().locator('[data-print-error]').textContent(), '') }
  const preview = () => dialog().locator('[data-print-preview]').evaluate(frame => {
    const doc = new DOMParser().parseFromString(frame.srcdoc, 'text/html')
    return { pages: doc.querySelectorAll('.page').length, text: doc.body.textContent, papers: [...doc.querySelectorAll('.page')].map(node => ({ width: node.style.width, height: node.style.height })), html: frame.srcdoc }
  })
  const tab = name => page.locator('[data-u-comp="slide-tab-item"]').filter({ hasText: name })
  stage = 'open'; await page.goto(origin + info.openPath); await ready()
  const nameBox = page.locator('[data-u-comp="defined-name"] input')
  let manual, adopted, selected, workbook, finalPreview, output, fit
  if (!resumeDirectory) {
  stage = 'manual'; await nameBox.fill('D95'); await nameBox.press('Enter'); await page.keyboard.type('Manual print draft'); await page.keyboard.press('Enter')
  await nameBox.fill('D95'); await nameBox.press('Enter'); await command('Home', 'bold')
  await page.waitForFunction(() => Object.entries(localStorage).some(([key, value]) => key.startsWith('native-editor-draft:') && (JSON.parse(value).operations ?? []).some(operation => operation.kind === 'applyCellEdits' && operation.edits.some(edit => edit.row === 94 && edit.column === 3 && edit.style?.bold === true))))
  manual = await draft()
  stage = 'initial'; await openPrint()
  await page.waitForFunction(() => document.querySelector('[data-print-scope] option[value=selection]')?.disabled === true)
  const initialSelection = await dialog().locator('[data-print-scope] option[value=selection]').evaluate(option => ({ disabled: option.disabled, html: option.outerHTML, nameBox: document.querySelector('[data-u-comp="defined-name"] input')?.value }))
  await writeFile(join(directory, 'initial-selection.json'), JSON.stringify(initialSelection, null, 2)); assert.equal(initialSelection.disabled, true)
  assert.equal(await dialog().locator('[data-print-orientation]').inputValue(), 'landscape')
  assert.equal(await dialog().locator('[data-print-scaling]').inputValue(), 'fit-file')
  assert.equal(await dialog().locator('[data-print-margins]').inputValue(), 'custom')
  assert.equal(await dialog().locator('[data-print-paper] option').count(), 9)
  assert((await preview()).pages >= 3)
  await dialog().locator('[data-print-cancel]').click(); assert.deepEqual(await draft(), manual)
  await openPrint(); await page.keyboard.press('Escape'); await dialog().waitFor({ state: 'hidden' }); assert.deepEqual(await draft(), manual)
  stage = 'selection'; await nameBox.fill('A1:D10'); await nameBox.press('Enter'); await openPrint(); await select('scope', 'selection')
  selected = await preview(); assert(selected.text.includes('Print row 10')); assert(!selected.text.includes('Print row 11'))
  await select('scope', 'workbook'); workbook = await preview(); assert(workbook.text.includes('Other printable')); assert(!workbook.text.includes('Never print hidden sheet'))
  await select('scope', 'active'); assert.deepEqual(await draft(), manual)
  stage = 'stale-target'; await tab('Other').dispatchEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true })
  await dialog().locator('[data-print-paper]').selectOption('8')
  await page.waitForFunction(() => /变化|重新/.test(document.querySelector('[data-print-error]')?.textContent ?? ''))
  assert.deepEqual(await draft(), manual); await dialog().locator('[data-print-cancel]').click(); await tab('Print').click()
  stage = 'settings'; await openPrint()
  await select('orientation', 'portrait'); await select('orientation', 'landscape')
  await select('paper', '13'); await select('margins', 'narrow')
  for (const mode of ['sheet', 'columns', 'rows', 'fit-file', 'none', 'custom']) await select('scaling', mode)
  const scale = dialog().locator('[data-print-scale]'); await scale.fill('401'); await scale.press('Tab')
  await page.waitForFunction(() => /10/.test(document.querySelector('[data-print-error]')?.textContent ?? ''))
  await scale.fill('70'); await scale.press('Tab'); await previewReady()
  for (const field of ['gridlines', 'headings']) { await dialog().locator(`[data-print-${field}]`).check(); await previewReady() }
  stage = 'header-footer'; await dialog().locator('[data-print-page-setup]').click()
  const hf = page.getByRole('dialog', { name: '页眉页脚', exact: true }); await hf.waitFor()
  await hf.locator('[data-header-footer-field="header-center"]').fill('Updated &P/&N')
  await hf.locator('[data-header-footer-apply]').click(); await hf.waitFor({ state: 'hidden' }); await previewReady()
  assert((await preview()).html.includes('Updated'))
  await dialog().locator('[data-print-zoom]').click(); assert.equal(await dialog().locator('[data-print-preview]').evaluate(frame => frame.style.transform), 'scale(1)')
  await dialog().locator('[data-print-zoom]').click()
  await dialog().locator('[data-print-next]').click(); assert.match(await dialog().locator('[data-print-page]').textContent(), /^2 \/ /)
  await dialog().locator('[data-print-refresh]').click(); await previewReady()
  await page.screenshot({ path: join(directory, 'print-dialog-desktop.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  fit = await dialog().locator('.workbook-print-preview-dialog').evaluate(node => { const box = node.getBoundingClientRect(); return { left: box.left, right: box.right, viewport: innerWidth, scrollWidth: node.scrollWidth, clientWidth: node.clientWidth } })
  assert(fit.left >= 0 && fit.right <= fit.viewport && fit.scrollWidth <= fit.clientWidth + 1, JSON.stringify(fit))
  await page.screenshot({ path: join(directory, 'print-dialog-mobile.png'), fullPage: true }); await page.setViewportSize({ width: 1760, height: 1100 })
  finalPreview = await preview(); assert(finalPreview.pages >= 3)
  stage = 'print-range'; await dialog().locator('[data-print-pages-mode]').selectOption('range')
  await dialog().locator('[data-print-from]').fill('3'); await dialog().locator('[data-print-from]').press('Tab')
  await dialog().locator('[data-print-to]').fill('2'); await dialog().locator('[data-print-to]').press('Tab')
  assert.equal(await dialog().locator('[data-print-submit]').isDisabled(), true)
  await dialog().locator('[data-print-from]').fill('2'); await dialog().locator('[data-print-from]').press('Tab')
  await dialog().locator('[data-print-to]').fill('3'); await dialog().locator('[data-print-to]').press('Tab')
  await dialog().locator('[data-print-pdf]').click(); await dialog().waitFor({ state: 'hidden' })
  const html = await page.evaluate(() => window.__printDialogHtml); assert(html)
  await writeFile(join(directory, 'selected-pages.html'), html)
  output = await page.evaluate(html => { const doc = new DOMParser().parseFromString(html, 'text/html'); return { pages: doc.querySelectorAll('.page').length, text: doc.body.textContent } }, html)
  assert.equal(output.pages, 2); assert(!output.text.includes('Never print hidden sheet'))
  const pdf = await browser.newPage(); await pdf.setContent(html, { waitUntil: 'load' }); await pdf.pdf({ path: join(directory, 'selected-pages.pdf'), preferCSSPageSize: true, printBackground: true }); await pdf.close()
  adopted = await draft(); assert.deepEqual(adopted.filter(operation => operation.kind === 'applyCellEdits'), manual)
  } else {
    adopted = JSON.parse(resumedDrafts[0][1]).operations
    manual = adopted.filter(operation => operation.kind === 'applyCellEdits')
    assert.deepEqual(await draft(), adopted)
    await writeFile(join(directory, 'continuation.json'), JSON.stringify({ from: resumeDirectory, sourceSha256: fixtureIdentity.sourceSha256, completedEarlier: ['selection', 'hidden-sheet-exclusion', 'stale-target', 'settings', 'header-footer', 'desktop-mobile-layout', 'print-range', 'actual-spool-pdf'], earlierFailure: 'draft-recovery margin preset classification', adopted }, null, 2))
  }
  stage = 'draft-recovery'; await page.reload(); await ready(); await openPrint()
  assert.equal(await dialog().locator('[data-print-paper]').inputValue(), '13'); assert.equal(await dialog().locator('[data-print-scale]').inputValue(), '70')
  assert.equal(await dialog().locator('[data-print-margins]').inputValue(), 'narrow'); assert.equal(await dialog().locator('[data-print-gridlines]').isChecked(), true)
  assert((await preview()).html.includes('Updated'))
  await page.setViewportSize({ width: 390, height: 844 }); await dialog().locator('[data-print-cancel]').scrollIntoViewIfNeeded()
  const mobileCancel = await dialog().locator('[data-print-cancel]').boundingBox(); assert(mobileCancel && mobileCancel.y >= 0 && mobileCancel.y + mobileCancel.height <= 844)
  await page.screenshot({ path: join(directory, 'print-dialog-mobile-actions.png'), fullPage: true })
  await dialog().locator('[data-print-cancel]').click(); await page.setViewportSize({ width: 1760, height: 1100 }); assert.deepEqual(await draft(), adopted)
  stage = 'save'; const waiting = page.waitForResponse(response => response.url().endsWith('/api/save') && response.request().method() === 'POST')
  await page.locator('[data-action="save"]').click(); const response = await waiting, saved = await response.json(), request = response.request().postDataJSON()
  assert.equal(response.status(), 200, JSON.stringify(saved)); assert.equal(saved.revisionRegistered, true); assert.equal(saved.revision, info.context.revision + 1)
  assert.equal(request.expectedSha256, fixtureIdentity.sourceSha256); assert.deepEqual(request.operations, adopted)
  await writeFile(join(directory, 'save-checkpoint.json'), JSON.stringify({ request, saved }, null, 2))
  const [download] = await Promise.all([page.waitForEvent('download'), page.locator('[data-action="xlsx-download"]').click()]); await download.saveAs(join(directory, 'printed.xlsx'))
  assert.equal(await download.failure(), null); assert.equal(sha(await readFile(join(directory, 'printed.xlsx'))), saved.artifacts.xlsx.sha256)
  await writeFile(join(directory, 'download-checkpoint.json'), JSON.stringify({ sha256: sha(await readFile(join(directory, 'printed.xlsx'))), savedSha256: saved.artifacts.xlsx.sha256 }, null, 2))
  stage = 'reopen'; await page.goto(saved.editor.openUrl); await ready(); await openPrint()
  assert.equal(await dialog().locator('[data-print-paper]').inputValue(), '13'); assert.equal(await dialog().locator('[data-print-scale]').inputValue(), '70')
  assert((await preview()).html.includes('Updated')); await page.screenshot({ path: join(directory, 'print-dialog-reopened.png'), fullPage: true }); await dialog().locator('[data-print-cancel]').click()
  const reopened = await page.request.get(page.url() + '/api/file'); assert.equal(reopened.status(), 200); assert.equal(sha(await reopened.body()), saved.artifacts.xlsx.sha256)
  const verification = python([]); assert.equal(verification.status, 0, verification.stderr || verification.stdout)
  await writeFile(join(directory, 'independent-checkpoint.json'), verification.stdout)
  await Promise.all(checks); await writeFile(join(directory, 'asset-checkpoint.json'), JSON.stringify(Object.fromEntries(assets), null, 2))
  await Promise.all(checks); assert(assets.size > 0); assert.deepEqual(errors, []); assert.deepEqual(consoleErrors, []); assert.deepEqual(httpErrors, []); assert.deepEqual(assetErrors, [])
  assert.equal(sha(await readFile(join(staticDirectory, '.vite/manifest.json'))), sha(manifest)); assert.equal(sha(await readFile(join(engineDirectory, 'dist/cli.mjs'))), sha(engine))
  const backendEnd = Object.fromEntries(await Promise.all(backendPaths.map(async path => [path, sha(await readFile(join(repo, path)))])))
  await writeFile(join(directory, 'backend-end-identities.json'), JSON.stringify(backendEnd, null, 2)); assert.deepEqual(backendEnd, backend)
  const state = await (await page.request.get(origin + '/__smoke__/state')).json(); assert.equal(state.plannerCalls, 0); assert.equal(state.savedRevisions, 1)
  const evidence = { ok: true, browserVersion: browser.version(), preflight, sourceSha256: fixtureIdentity.sourceSha256, manifestSha256: sha(manifest), engineSha256: sha(engine), nativeOfficeSha256, backendExecution: 'live workspace files; SHA-256 verified before and after HTTP chain', backend, backendEnd, assets: Object.fromEntries(assets),
    continuationFrom: resumeDirectory ?? null, fit, selectedPages: selected?.pages, workbookPages: workbook?.pages, finalPages: finalPreview?.pages, output, manual, adopted, request, saved, independent: JSON.parse(verification.stdout), errors, consoleErrors, httpErrors, assetErrors, state }
  await writeFile(join(directory, 'evidence.json'), JSON.stringify(evidence, null, 2)); console.log(JSON.stringify({ ok: true, directory, assets: assets.size, independent: evidence.independent }))
} catch (error) {
  await writeFile(join(directory, 'failure.json'), JSON.stringify({ stage, error: String(error), stack: error.stack, serverLog, errors, consoleErrors, httpErrors, assetErrors,
    diagnostics: page ? await page.evaluate(() => ({ printError: document.querySelector('[data-print-error]')?.textContent, page: document.querySelector('[data-print-page]')?.textContent, nameBox: document.querySelector('[data-u-comp="defined-name"] input')?.value, selectionOption: document.querySelector('[data-print-scope] option[value=selection]')?.outerHTML, drafts: Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')), feedback: document.querySelector('.workbook-feedback')?.textContent })).catch(() => null) : null }, null, 2))
  await page?.screenshot({ path: join(directory, 'failure.png'), fullPage: true }).catch(() => {}); throw error
} finally { await browser?.close(); server.kill('SIGTERM'); await writeFile(join(directory, 'server.log'), serverLog) }
