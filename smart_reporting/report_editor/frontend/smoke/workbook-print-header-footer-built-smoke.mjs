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
const port = Number(process.env.PRINT_HEADER_FOOTER_SMOKE_PORT ?? 4287)
const base = `http://127.0.0.1:${port}`
const temporary = await mkdtemp(join(tmpdir(), 'print-header-footer-built-'))
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
const fixture = spawnSync(join(repo, '.venv/bin/python'), ['-c', `
from openpyxl import Workbook
from openpyxl.worksheet.pagebreak import Break
from io import BytesIO
import sys
b=Workbook();s=b.active;s.title='Header <sheet>'
for r in range(1,4):s.cell(r,1,f'Body {r}')
s.print_area='A1:B3';s.page_setup.scale=50
s.row_breaks.append(Break(id=1));s.row_breaks.append(Break(id=2))
s.oddHeader.left.text='Odd &P';s.oddHeader.center.text='Total &N';s.oddHeader.right.text='&A'
s.oddFooter.center.text='&F && literal <script>alert(1)</script> &G'
s.firstHeader.center.text='First &P/&N';s.evenHeader.center.text='Even &P/&N'
s.HeaderFooter.differentFirst=True;s.HeaderFooter.differentOddEven=True;s.HeaderFooter.scaleWithDoc=True
s.page_margins.header=0.2;s.page_margins.footer=0.25
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
    if (req.url.endsWith('/api/context')) { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ context: { documentId: 'print-header-footer-built', format: 'xlsx', revision: 1, parentRevision: 0, scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' }, sourceFile: { path: 'header-footer.xlsx', size: bytes.length, sha256: sha(bytes), mediaType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }, origin: 'upload' }, csrfToken: 'csrf', capabilities: { xlsx_editor: true }, editingEnabled: true })); return }
    const path = req.url === '/reports/v1/native/print-header-footer-built/1' ? '/reports/v1/editor/assets/native.html' : req.url
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
      for (const node of nodes) if (node instanceof HTMLIFrameElement && node.contentWindow) node.contentWindow.print = () => { window.__printHeaderFooterHtml = node.contentDocument.documentElement.outerHTML }
    }
  })
  stage('browser-launched')
  await page.goto(`http://127.0.0.1:${http.address().port}/reports/v1/native/print-header-footer-built/1`)
  await page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 60000 })
  stage('editor-ready')
  await page.locator('[data-ribbon-tab=File]').click()
  await page.locator('[data-ribbon-command=print]').click()
  await page.waitForFunction(() => window.__printHeaderFooterHtml)
  stage('print-intercepted')
  const html = await page.evaluate(() => window.__printHeaderFooterHtml)
  await writeFile(join(temporary, 'print.html'), html)
  const result = await page.evaluate(html => {
    const doc = new DOMParser().parseFromString(html, 'text/html')
    return [...doc.querySelectorAll('.page')].map(page => ({
      header: [...page.querySelectorAll('.hf-header span')].map(span => span.textContent),
      footer: [...page.querySelectorAll('.hf-footer span')].map(span => span.textContent),
      headerCss: page.querySelector('.hf-header')?.getAttribute('style'),
      scriptCount: page.querySelectorAll('script, img').length,
    }))
  }, html)
  assert.equal(result.length, 3)
  assert.deepEqual(result[0].header, ['', 'First 1/3', ''])
  assert.deepEqual(result[0].footer, [])
  assert.deepEqual(result[1].header, ['', 'Even 2/3', ''])
  assert.deepEqual(result[1].footer, [])
  assert.deepEqual(result[2].header, ['Odd 3', 'Total 3', 'Header <sheet>'])
  assert.deepEqual(result[2].footer, ['', 'header-footer.xlsx & literal <script>alert(1)</script> ', ''])
  for (const record of result) {
    assert.equal(record.scriptCount, 0)
    assert.match(record.headerCss, /top:0.2in/)
    assert.match(record.headerCss, /font-size:4.5pt/)
  }
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
  console.log(JSON.stringify({ ...report, assets: Object.keys(assets).length }))
} finally { await browser?.close(); preview?.kill(); http.close() }
