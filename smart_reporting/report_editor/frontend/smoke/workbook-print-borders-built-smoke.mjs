import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdtemp, readFile, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.PRINT_BORDERS_SMOKE_PORT ?? 4283)
const base = `http://127.0.0.1:${port}`
const temporary = await mkdtemp(join(tmpdir(), 'print-borders-built-'))
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
const fixture = spawnSync(join(repo, '.venv/bin/python'), ['-c', `
from openpyxl import Workbook
from openpyxl.styles import Border, Side
from io import BytesIO
import sys
b=Workbook();s=b.active;s.title='Print borders'
s['A1']='Edges';s['A1'].border=Border(top=Side(style='thin',color='123456'),bottom=Side(style='medium',color='ABCDEF'),left=Side(style='thick',color='222222'),right=Side(style='double',color='654321'))
s['B1']='Right';s['B1'].border=Border(left=Side(style='thick',color='FF0000'))
s['A3']='Merged';s.merge_cells('A3:B4');s['A3'].border=Border(top=Side(style='thin',color='009900'),bottom=Side(style='medium',color='009900'),left=Side(style='thick',color='009900'),right=Side(style='thick',color='009900'))
s['C3']='Merge neighbour';s['C3'].border=Border(left=Side(style='thin',color='0000FF'))
s['A6']=1234.567;s['A6'].number_format='#,##0.00'
s.row_dimensions[1].height=30;s.column_dimensions['A'].width=20;s.column_dimensions['B'].width=20
s.print_area='A1:C6';s.print_options.gridLines=True;s.page_setup.scale=100
f=BytesIO();b.save(f);sys.stdout.buffer.write(f.getvalue())
`], { cwd: repo })
assert.equal(fixture.status, 0, fixture.stderr.toString())
const bytes = fixture.stdout
await writeFile(join(temporary, 'source.xlsx'), bytes)
const errors = [], assets = {}, checks = []
const stage = name => console.log(JSON.stringify({ stage: name, temporary }))
stage('fixture-created')
let browser, preview
const http = createServer(async (req, res) => {
  try {
    if (req.url.endsWith('/api/file')) { res.writeHead(200, { 'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }); res.end(bytes); return }
    if (req.url.endsWith('/api/context')) { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ context: { documentId: 'print-borders-built', format: 'xlsx', revision: 1, parentRevision: 0, scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' }, sourceFile: { path: 'borders.xlsx', size: bytes.length, sha256: sha(bytes), mediaType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }, origin: 'upload' }, csrfToken: 'csrf', capabilities: { xlsx_editor: true }, editingEnabled: true })); return }
    const path = req.url === '/reports/v1/native/print-borders-built/1' ? '/reports/v1/editor/assets/native.html' : req.url
    const response = await fetch(base + path, { signal: AbortSignal.timeout(15000) })
    res.writeHead(response.status, Object.fromEntries([...response.headers].filter(([key]) => !['content-encoding', 'content-length', 'transfer-encoding'].includes(key))))
    res.end(Buffer.from(await response.arrayBuffer()))
  } catch (error) { res.writeHead(500); res.end(String(error)) }
})
await new Promise(resolve => http.listen(0, '127.0.0.1', resolve))
try {
  stage('server-listening')
  preview = spawn('./node_modules/.bin/vite', ['preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'pipe' })
  for (let index = 0; ; index++) {
    assert.equal(preview.exitCode, null)
    try { if ((await fetch(base + '/reports/v1/editor/assets/native.html', { signal: AbortSignal.timeout(5000) })).ok) break } catch {}
    assert(index < 100); await delay(250)
  }
  stage('preview-ready')
  browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } })
  page.on('pageerror', error => errors.push(error.message))
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (!path.startsWith('/reports/v1/editor/assets/') || !path.endsWith('.js')) return
    checks.push((async () => { const body = await response.body(); assert.equal(sha(body), sha(await readFile(join(frontend, '../static', path.slice('/reports/v1/editor/assets/'.length))))); assets[path] = sha(body) })())
  })
  await page.addInitScript(() => {
    const append = Element.prototype.append
    Element.prototype.append = function (...nodes) {
      append.apply(this, nodes)
      for (const node of nodes) if (node instanceof HTMLIFrameElement && node.contentWindow) node.contentWindow.print = () => { window.__printBordersHtml = node.contentDocument.documentElement.outerHTML }
    }
  })
  stage('browser-launched')
  await page.goto(`http://127.0.0.1:${http.address().port}/reports/v1/native/print-borders-built/1`)
  await page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 60000 })
  stage('editor-ready')
  await page.locator('[data-ribbon-tab=File]').click()
  await page.locator('[data-ribbon-command=print]').click()
  await page.waitForFunction(() => window.__printBordersHtml)
  stage('print-intercepted')
  const html = await page.evaluate(() => window.__printBordersHtml)
  await writeFile(join(temporary, 'print.html'), html)
  const result = await page.evaluate(html => {
    const doc = new DOMParser().parseFromString(html, 'text/html')
    const cells = [...doc.querySelectorAll('td')]
    return { edges: cells.find(cell => cell.textContent === 'Edges')?.getAttribute('style'), right: cells.find(cell => cell.textContent === 'Right')?.getAttribute('style'), merged: cells.filter(cell => cell.textContent === 'Merged').map(cell => ({ rows: cell.rowSpan, columns: cell.colSpan, shadow: cell.getAttribute('style') })), mergeNeighbour: cells.find(cell => cell.textContent === 'Merge neighbour')?.getAttribute('style'), formatted: cells.some(cell => cell.textContent === '1,234.57') }
  }, html)
  assert.match(result.edges, /0 0.75pt 0 #123456/)
  assert.match(result.edges, /0 -1.5pt 0 #abcdef/i)
  assert.match(result.edges, /2.25pt 0 0 #222222/)
  assert(!/#ff0000/i.test(result.right), 'left cell owns conflicting shared edge')
  assert.equal(result.merged.length, 1); assert.equal(result.merged[0].rows, 2); assert.equal(result.merged[0].columns, 2)
  assert.match(result.merged[0].shadow, /2.25pt 0 0 #009900/)
  assert(!/#0000ff/i.test(result.mergeNeighbour), 'merged anchor owns conflicting shared edge')
  assert.equal(result.formatted, true)
  stage('html-assertions-passed')
  await page.screenshot({ path: join(temporary, 'native-print-entry.png'), fullPage: true })
  const printPage = await browser.newPage({ viewport: { width: 1000, height: 1200 } })
  await printPage.setContent(html); await printPage.emulateMedia({ media: 'print' })
  await printPage.screenshot({ path: join(temporary, 'print-rendering.png'), fullPage: true })
  await printPage.pdf({ path: join(temporary, 'print.pdf'), preferCSSPageSize: true, printBackground: true })
  stage('screenshots-pdf-written')
  await Promise.all(checks); assert.deepEqual(errors, [])
  const report = { ok: true, temporary, browser: browser.version(), result, assets, errors }
  await writeFile(join(temporary, 'result.json'), JSON.stringify(report, null, 2))
  console.log(JSON.stringify(report))
} finally { await browser?.close(); preview?.kill(); http.close() }
