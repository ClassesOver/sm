import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFileSync, writeFileSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.PAGE_BREAK_SMOKE_PORT ?? 4257)
const base = `http://127.0.0.1:${port}`
const temporary = mkdtempSync(join(tmpdir(), 'page-break-preview-built-'))
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
function fixture() {
  const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import base64
from io import BytesIO
from openpyxl import Workbook
from openpyxl.worksheet.pagebreak import Break
b=Workbook();b.remove(b.active)
for name in ['Plain','Frozen','Zoom150','RTL']:
 s=b.create_sheet(name)
 for row in range(1,71):
  for col in range(1,9):s.cell(row,col,f'{row}:{col}')
 s.print_area='A1:H70';s.print_title_rows='1:2';s.row_breaks.append(Break(id=25))
 s.page_setup.paperSize='9';s.page_setup.scale=90
 s.row_dimensions[5].hidden=True;s.column_dimensions['C'].hidden=True
 if name=='Frozen':s.freeze_panes='C3'
 if name=='Zoom150':s.sheet_view.zoomScale=150
 if name=='RTL':s.sheet_view.rightToLeft=True
 s.protection.sheet=True
f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
`], { cwd: repo, encoding: 'utf8' })
  assert.equal(result.status, 0, result.stderr)
  return Buffer.from(result.stdout.trim(), 'base64')
}
const bytes = fixture()
const media = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const context = { documentId: 'page-break-preview', format: 'xlsx', revision: 1, parentRevision: null, scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' }, sourceFile: { path: 'page-break-preview.xlsx', size: bytes.length, sha256: sha(bytes), mediaType: media }, origin: 'upload' }
const server = spawn('./node_modules/.bin/vite', ['preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
// Serve API bytes over real HTTP: Chromium cancels route-fulfilled downloads.
const downloadServer = createServer(async (request, response) => {
  if (request.url === '/reports/v1/native/page-break-preview/1/api/file') { response.writeHead(200, { 'Content-Type': media, 'Content-Disposition': 'attachment; filename=page-break-preview.xlsx', 'Content-Length': bytes.length }); response.end(bytes); return }
  if (request.url === '/reports/v1/native/page-break-preview/1/api/context') { response.writeHead(200, { 'Content-Type': 'application/json' }); response.end(JSON.stringify({ context, csrfToken: 'csrf', capabilities: { xlsx_editor: true }, editingEnabled: true })); return }
  try { const upstream = await fetch(`${base}${request.url === '/reports/v1/native/page-break-preview/1' ? '/reports/v1/editor/assets/native.html' : request.url}`); response.writeHead(upstream.status, Object.fromEntries([...upstream.headers].filter(([key]) => !['content-encoding', 'content-length', 'transfer-encoding'].includes(key)))); response.end(Buffer.from(await upstream.arrayBuffer())) }
  catch { response.writeHead(502); response.end() }
})
await new Promise(resolve => downloadServer.listen(0, '127.0.0.1', resolve))
const applicationBase = `http://127.0.0.1:${downloadServer.address().port}`
let browser, page, stage = 'setup', saveCount = 0
try {
  for (let i = 0; i < 120; i++) { try { if ((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true })
  page = await browser.newPage({ viewport: { width: 1500, height: 1100 }, colorScheme: 'light', acceptDownloads: true, permissions: ['clipboard-read', 'clipboard-write'] })
  const errors = [], scripts = [], results = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('response', response => {
    const url = new URL(response.url())
    if (url.pathname.startsWith('/reports/v1/editor/assets/') && url.pathname.endsWith('.js')) scripts.push((async () => {
      assert.equal(response.status(), 200)
      assert.equal(sha(await response.body()), sha(readFileSync(join(frontend, '../static', url.pathname.slice('/reports/v1/editor/assets/'.length)))))
      return url.pathname
    })())
  })
  await page.route('**/reports/v1/native/page-break-preview/1/api/save', route => { saveCount++; return route.fulfill({ status: 500, json: { detail: 'Reading view must never save' } }) })
  await page.addInitScript(() => { if (window === window.top) history.replaceState(null, '', '/reports/v1/native/page-break-preview/1') })
  const ready = async () => { await page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 60000 }); await page.locator('[data-ribbon-tab="Home"]').waitFor() }
  const goto = async reference => { await page.locator('[data-ribbon-tab="Home"]').click(); await page.locator('[data-ribbon-command="goto-open"]').click(); await page.locator('[data-goto-reference]').fill(reference); await page.locator('.workbook-ribbon-goto-dialog button[type="submit"]').click(); await delay(250) }
  const view = () => page.locator('[data-ribbon-tab="View"]').click()
  const toggle = async enabled => {
    await view()
    await page.locator(`[data-ribbon-command="${enabled ? 'toggle-page-break-preview' : 'normal-view'}"]`).click()
    await page.waitForFunction(enabled => document.querySelector('[data-ribbon-command="toggle-page-break-preview"]')?.getAttribute('aria-pressed') === String(enabled), enabled)
    if (enabled) await page.locator('.workbook-page-break-page').first().waitFor()
    else await page.waitForFunction(() => document.querySelectorAll('.workbook-page-break-preview').length === 0)
    await delay(200)
  }
  const state = async () => {
    await page.locator('[data-ribbon-tab="File"]').click()
    return { storage: await page.evaluate(() => ({ ...localStorage })), label: await page.locator('.save-state-label').textContent(), undo: await page.locator('[data-ribbon-command="undo"]').isDisabled(), redo: await page.locator('[data-ribbon-command="redo"]').isDisabled() }
  }
  const sourceHash = async () => sha(Buffer.from(await page.evaluate(async () => Array.from(new Uint8Array(await (await fetch('/reports/v1/native/page-break-preview/1/api/file')).arrayBuffer())))))
  const downloadHash = async suffix => { const [download] = await Promise.all([page.waitForEvent('download'), page.locator('[data-action="xlsx-download"]').click()]); const path = await download.path(); assert(path, String(await download.failure())); const downloaded = readFileSync(path); writeFileSync(join(temporary, `downloaded-${suffix}.xlsx`), downloaded); return sha(downloaded) }
  await page.goto(`${applicationBase}/reports/v1/editor/assets/native.html`); await ready()
  await goto('Plain!A1')
  const baseline = await state(), beforeHash = await sourceHash()
  assert.equal(beforeHash, sha(bytes)); assert.equal(await downloadHash('before'), beforeHash)
  for (const name of ['Plain', 'Frozen', 'Zoom150', 'RTL']) {
    stage = name
    await goto(`${name}!A1`); await view()
    if (name !== 'Plain') assert.equal(await page.locator('[data-ribbon-command="normal-view"]').getAttribute('aria-pressed'), 'true')
    assert.equal(await page.locator('[data-ribbon-command="toggle-page-break-preview"]').isDisabled(), false)
    await toggle(true)
    const layers = await page.locator('.workbook-page-break-preview').evaluateAll(items => items.map(item => ({ kind: item.className, width: item.getBoundingClientRect().width, height: item.getBoundingClientRect().height, text: item.textContent })))
    assert(layers.some(layer => layer.text?.includes('第 1 页') && layer.width > 0 && layer.height > 0), `${name}: real page watermark geometry`)
    assert(layers.some(layer => layer.kind.includes('outline')), `${name}: outline installed`)
    await page.screenshot({ path: join(temporary, `${name}-preview.png`), fullPage: true })
    await toggle(false)
    assert.deepEqual(await state(), baseline, `${name}: preview must not modify local draft/history/save status`)
    results.push({ name, layers: layers.length, pageWatermark: true, cleanNormalView: true })
  }
  // Per-Worksheet mode survives activation; a different sheet starts in normal view.
  await goto('Plain!A1'); await toggle(true)
  await goto('Frozen!A1'); await view()
  await page.waitForFunction(() => document.querySelectorAll('.workbook-page-break-preview').length === 0)
  await goto('Plain!A1'); await view(); await page.locator('.workbook-page-break-page').first().waitFor()
  await toggle(false)
  assert.equal(await sourceHash(), beforeHash); assert.equal(await downloadHash('after'), beforeHash); assert.equal(saveCount, 0)
  const assets = await Promise.all(scripts); assert(assets.some(path => /workbook-main-/.test(path))); assert.deepEqual(errors, [])
  writeFileSync(join(temporary, 'source.xlsx'), bytes)
  console.log(JSON.stringify({ ok: true, temporary, builtJs200AndSha: assets.length, cases: results, protectedReadonlySheets: true, perWorksheetMode: true, draftHistoryAndSaveStateUnchanged: true, sourceAndDownloadedSha256Unchanged: beforeHash, saveCount, pageErrors: errors }))
} catch (error) {
  await page?.screenshot({ path: join(temporary, 'failure.png'), fullPage: true }).catch(() => {})
  console.error(JSON.stringify({ stage, temporary })); throw error
} finally { await browser?.close(); server.kill(); downloadServer.close() }
