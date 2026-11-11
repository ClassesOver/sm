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
const port = Number(process.env.PAGE_BREAK_EDITABLE_SMOKE_PORT ?? 4258)
const base = `http://127.0.0.1:${port}`
const temporary = mkdtempSync(join(tmpdir(), 'page-break-editable-built-'))
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
function python(input) {
  const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import base64,json,sys
from io import BytesIO
from zipfile import ZipFile
from openpyxl import load_workbook
p=json.load(sys.stdin)
if p['mode']=='patch':
 from smart_reporting.report_editor.native_office import patch_office
 print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 b=load_workbook(BytesIO(base64.b64decode(p['bytes'])));s=b['Editable']
 with ZipFile(BytesIO(base64.b64decode(p['bytes']))) as z:
  xml=z.read('xl/worksheets/sheet1.xml').decode();names=z.read('xl/workbook.xml').decode()
 print(json.dumps({'area':str(s.print_area),'titles':s.print_title_rows,'rows':[x.id for x in s.row_breaks.brk],'cols':[x.id for x in s.col_breaks.brk],'height':s.row_dimensions[4].height,'width':s.column_dimensions['E'].width,'hiddenRows':[i for i,v in s.row_dimensions.items() if v.hidden],'hiddenCols':[i for i,v in s.column_dimensions.items() if v.hidden],'xml':xml,'names':names}))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  assert.equal(result.status, 0, result.stderr)
  return result.stdout.trim()
}
function fixture() {
  const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import base64
from io import BytesIO
from openpyxl import Workbook
from openpyxl.worksheet.pagebreak import Break
b=Workbook();b.remove(b.active)
for name in ['Editable']:
 s=b.create_sheet(name)
 for row in range(1,71):
  for col in range(1,9):s.cell(row,col,f'{row}:{col}')
 s.print_area='A1:H70';s.print_title_rows='1:2';s.row_breaks.append(Break(id=25))
 s.page_setup.paperSize='9';s.page_setup.scale=90
 s.row_dimensions[5].hidden=True;s.column_dimensions['C'].hidden=True
 if name=='Frozen':s.freeze_panes='C3'
 if name=='Zoom150':s.sheet_view.zoomScale=150
 if name=='RTL':s.sheet_view.rightToLeft=True
 s.protection.sheet=False
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
let savedBytes, savePayload
const downloadServer = createServer(async (request, response) => {
  if (request.url === '/saved-page-break.xlsx' && savedBytes) { response.writeHead(200, { 'Content-Type': media, 'Content-Disposition': 'attachment; filename=saved-page-break.xlsx' }); response.end(savedBytes); return }
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
  await page.route('**/reports/v1/native/page-break-preview/1/api/save', async route => {
    saveCount++; savePayload = route.request().postDataJSON()
    savedBytes = Buffer.from(python({ mode: 'patch', bytes: bytes.toString('base64'), operations: savePayload.operations }), 'base64')
    await route.fulfill({ json: { documentId: context.documentId, revision: 2, parentRevision: 1, revisionRegistered: true,
      artifacts: { xlsx: { downloadUrl: '/saved-page-break.xlsx', size: savedBytes.length, sha256: sha(savedBytes) } },
      editor: { openUrl: '/reports/v1/native/page-break-preview/2' }, validation: { ok: true, issues: [] } } })
  })
  await page.addInitScript(() => {
    const append = Element.prototype.append
    Element.prototype.append = function (...nodes) {
      append.apply(this, nodes)
      for (const node of nodes) if (node instanceof HTMLIFrameElement && node.contentWindow) node.contentWindow.print = () => { window.__pageBreakPrint = node.contentDocument.documentElement.outerHTML }
    }
  })
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
  const command = async (tab, id) => { await page.locator(`[data-ribbon-tab="${tab}"]`).click(); await page.locator(`[data-ribbon-command="${id}"]`).click(); await delay(250) }
  const menu = async (name, value) => { await page.locator('[data-ribbon-tab="Page Layout"]').click(); await page.locator(`[data-ribbon-menu="${name}"]`).selectOption(value); await delay(250) }
  const size = async (reference, axis, value) => { await goto(reference); await command('Home', `${axis === 'row' ? 'row-height' : 'col-width'}-open`); await page.locator('.workbook-ribbon-axis-value').fill(String(value)); await page.locator('.workbook-ribbon-axis-dialog button[type="submit"]').click(); await delay(250) }
  const printParity = async label => {
    await view(); await page.locator('.workbook-page-break-page').first().waitFor()
    const previewPages = [...new Set(await page.locator('.workbook-page-break-page').allTextContents())].length
    await page.evaluate(() => { window.__pageBreakPrint = undefined })
    await command('File', 'print')
    await page.waitForFunction(() => !!window.__pageBreakPrint)
    const html = await page.evaluate(() => window.__pageBreakPrint)
    const printPages = await page.evaluate(html => new DOMParser().parseFromString(html, 'text/html').querySelectorAll('.page').length, html)
    assert.equal(previewPages, printPages, `${label}: actual preview page count must equal actual File Print HTML pages`)
    const content = await page.evaluate(html => {
      const doc = new DOMParser().parseFromString(html, 'text/html')
      return { titles: [...doc.querySelectorAll('.page table')].map(table => table.querySelector('tr')?.textContent), cells: [...doc.querySelectorAll('td')].map(cell => cell.textContent), rows: [...doc.querySelectorAll('tr')].map(row => row.style.height), columns: [...doc.querySelectorAll('col')].map(col => parseFloat(col.style.width)) }
    }, html)
    assert(content.titles.every(title => /1:\d/.test(title)), `${label}: actual print repeats authored first-row title on each page`)
    if (label === 'live-size-hidden') {
      assert(content.rows.includes('37.8pt'), 'live row 42pt must print at original 90% scale')
      assert(content.columns.some(width => width > 90), 'live wide visible column must affect print geometry')
      assert(content.cells.every(value => !/^(?:5|6):/.test(value)), 'hidden rows must be excluded from actual print')
      assert(content.cells.every(value => !/:([356])$/.test(value)), 'source and newly hidden columns must be excluded from actual print')
    }

    writeFileSync(join(temporary, `${label}-print.html`), html)
    results.push({ label, previewPages, printPages }); console.log(JSON.stringify(results.at(-1)))
  }
  stage = 'page-settings-before-structure'
  await goto('Editable!A1:H40'); await menu('print-area', 'print-area:set')
  await menu('print-titles', 'print-titles:first-row'); await menu('page-breaks', 'page-breaks:reset')
  await goto('Editable!D10'); await menu('page-breaks', 'page-breaks:insert')
  await toggle(true); await printParity('initial-settings')
  stage = 'insert-row-column'
  await goto('Editable!A3'); await command('Home', 'insert-row-here')
  await goto('Editable!B1'); await command('Home', 'insert-col-here')
  await printParity('inserted')
  stage = 'settings-after-structure'
  await goto('Editable!F15'); await menu('page-breaks', 'page-breaks:insert')
  await printParity('second-epoch-settings')
  stage = 'delete-undo-redo'
  await goto('Editable!A20'); await command('Home', 'delete-row-here')
  await goto('Editable!H1'); await command('Home', 'delete-col-here')
  await printParity('deleted')
  await command('File', 'undo'); await printParity('undo-column-delete')
  await command('File', 'redo'); await printParity('redo-column-delete')
  stage = 'live-dimensions-hidden'
  await size('Editable!A4', 'row', 42); await size('Editable!E1', 'col', 20)
  await goto('Editable!A6:A7'); await command('Data', 'outline-group:rows'); await command('Data', 'outline-hide-detail:rows')
  await goto('Editable!F1:G1'); await command('Data', 'outline-group:cols'); await command('Data', 'outline-hide-detail:cols')
  await printParity('live-size-hidden')
  await view(); await page.screenshot({ path: join(temporary, 'editable-final-preview.png'), fullPage: true })
  stage = 'save-download-zip'
  await page.locator('[data-action="save"]').click()
  await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 })
  assert.equal(saveCount, 1)
  assert(savePayload.operations.some(op => op.kind === 'applyRowColumnOps'), JSON.stringify(savePayload))
  const downloaded = Buffer.from(await page.evaluate(async () => Array.from(new Uint8Array(await (await fetch('/saved-page-break.xlsx')).arrayBuffer()))))
  assert.equal(sha(downloaded), sha(savedBytes))
  writeFileSync(join(temporary, 'saved.xlsx'), downloaded); writeFileSync(join(temporary, 'save-payload.json'), JSON.stringify(savePayload, null, 2))
  const zip = JSON.parse(python({ mode: 'inspect', bytes: downloaded.toString('base64') }))
  writeFileSync(join(temporary, 'zip-inspection.json'), JSON.stringify(zip, null, 2))
  assert.match(zip.area, /\$A\$1:\$H\$40/); assert.equal(zip.titles, '$1:$1')
  assert.deepEqual(zip.rows, [10, 14]); assert.deepEqual(zip.cols, [4, 5])
  assert.equal(zip.height, 42); assert(Math.abs(zip.width - 20) < .2, `saved column width ${zip.width}`)
  assert(zip.hiddenRows.includes(6) && zip.hiddenRows.includes(7), JSON.stringify(zip.hiddenRows))
  assert(zip.hiddenCols.includes('D') && zip.hiddenCols.includes('F') && zip.hiddenCols.includes('G'), JSON.stringify(zip.hiddenCols))
  assert(!savePayload.operations.some(op => op.kind === 'applyColumnWidths' && op.entries.some(entry => entry.index === 3)), 'unchanged source width must not create a stale-epoch geometry patch')
  assert.match(zip.xml, /rowBreaks/); assert.match(zip.xml, /colBreaks/); assert.match(zip.names, /_xlnm.Print_Area/); assert.match(zip.names, /_xlnm.Print_Titles/)
  writeFileSync(join(temporary, 'zip-inspection.json'), JSON.stringify(zip, null, 2))
  const assets = await Promise.all(scripts); assert(assets.some(path => /workbook-main-/.test(path))); assert.deepEqual(errors, [])
  writeFileSync(join(temporary, 'source.xlsx'), bytes)
  console.log(JSON.stringify({ ok: true, temporary, builtJs200AndSha: assets.length, cases: results, saveCount, savedDownloadSha256: sha(savedBytes), zip: { area: zip.area, titles: zip.titles, rows: zip.rows, cols: zip.cols, height: zip.height, width: zip.width, hiddenRows: zip.hiddenRows, hiddenCols: zip.hiddenCols }, pageErrors: errors }))
} catch (error) {
  await page?.screenshot({ path: join(temporary, 'failure.png'), fullPage: true }).catch(() => {})
  console.error(JSON.stringify({ stage, temporary })); throw error
} finally { await browser?.close(); server.kill(); downloadServer.close() }
