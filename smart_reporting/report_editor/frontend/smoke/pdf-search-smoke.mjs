import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.PDF_SEARCH_SMOKE_PORT ?? 4203), base = `http://127.0.0.1:${port}`
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
function python(input) {
  const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import json,sys,base64
from io import BytesIO
from pypdf import PdfReader,PdfWriter
from pypdf.generic import NameObject,NumberObject,DecodedStreamObject
from smart_reporting.reporting.tests.test_pdf_page_size import size_fixture
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf,patch_pdf_with_receipt
p=json.load(sys.stdin)
if p['mode']=='create':
 w=PdfWriter(clone_from=PdfReader(BytesIO(size_fixture())))
 for n,text in enumerate([b'BT /F1 12 Tf 1 0 0 1 30 430 Tm (cat cat scatter CAT cat_) Tj ET',b'BT /F1 12 Tf 1 0 0 1 30 430 Tm (cat invoice) Tj ET',b'']):
  s=DecodedStreamObject();s.set_data(text);w.pages[n][NameObject('/Contents')]=w._add_object(s)
 w.pages[0][NameObject('/UserUnit')]=NumberObject(2);w.pages[1][NameObject('/Rotate')]=NumberObject(90)
 out=BytesIO();w.write(out);b=out.getvalue();print(json.dumps({'bytes':base64.b64encode(b).decode(),'model':inspect_pdf(b)}))
else:
 b=base64.b64decode(p['bytes']);r=patch_pdf_with_receipt(b,p['operations']);r['bytes']=base64.b64encode(r.pop('content')).decode();r['model']=inspect_pdf(base64.b64decode(r['bytes']));print(json.dumps(r))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw Error(result.stderr)
  return JSON.parse(result.stdout)
}
const fixture = python({ mode: 'create' }), source = Buffer.from(fixture.bytes, 'base64')
let browser, previewBytes
const server = spawn('./node_modules/.bin/vite', ['preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
try {
  for (let n = 0; n < 100; n++) { try { if ((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true, executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ?? '/usr/bin/chromium' })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } }), errors = []
  page.on('pageerror', error => errors.push(error.message)); page.on('console', entry => { if (entry.type() === 'error') errors.push(entry.text()) })
  let readonly = false
  await page.route('**/reports/v1/native/search-fixture/1/api/context', route => route.fulfill({ json: {
    context: { documentId: 'search-fixture', revision: 1, parentRevision: null, format: 'pdf', origin: 'upload', scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' }, sourceFile: { path: 'search.pdf', size: source.length, sha256: sha(source), mediaType: 'application/pdf' } }, csrfToken: 'fixture', capabilities: { pdf_editor: true }, editingEnabled: !readonly,
  } }))
  await page.route('**/reports/v1/native/search-fixture/1/api/file', route => route.fulfill({ body: source, contentType: 'application/pdf' }))
  const patch = operations => python({ mode: 'patch', bytes: fixture.bytes, operations })
  await page.route('**/reports/v1/native/search-fixture/1/api/preview', route => {
    const ops = route.request().postDataJSON().operations, result = ops.length ? patch(ops) : null
    return route.fulfill({ json: { sourceSha256: sha(source), model: result?.model ?? fixture.model, appliedOperationIndices: result?.appliedOperationIndices ?? [], skippedOperations: [], previewDigest: result?.previewDigest } })
  })
  await page.route('**/reports/v1/native/search-fixture/1/api/preview.pdf', route => {
    const input = route.request().postDataJSON(), result = patch(input.operations); assert.equal(input.expectedPreviewDigest, result.previewDigest)
    previewBytes = Buffer.from(result.bytes, 'base64')
    return route.fulfill({ body: previewBytes, contentType: 'application/pdf', headers: { 'X-Native-Preview-Digest': result.previewDigest } })
  })
  await page.route('**/reports/v1/native/search-fixture/1', async route => route.fulfill({ response: await route.fetch({ url: `${base}/reports/v1/editor/assets/native.html` }) }))
  const open = async () => { await page.goto(`${base}/reports/v1/native/search-fixture/1`); await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 3 && document.querySelector('.pdf-page canvas'), null, { timeout: 60000 }) }
  const count = page.getByLabel('搜索匹配计数'), search = page.getByLabel('搜索 PDF 文字'), next = page.getByRole('button', { name: '下一处', exact: true })
  const waitCount = value => page.waitForFunction(value => document.querySelector('[aria-label="搜索匹配计数"]')?.textContent === value, value)
  const waitActive = pageId => page.waitForFunction(pageId => document.querySelector('.pdf-page.is-active')?.dataset.pageId === pageId, pageId)
  const ops = () => page.evaluate(() => Object.entries(localStorage).filter(([key]) => key.includes('search-fixture')).map(([, value]) => JSON.parse(value).operations))
  await open(); const beforeDraft = await ops()
  await search.fill('cat'); await waitCount('1 / 6')
  await page.waitForFunction(() => document.querySelector('.pdf-page')?.querySelectorAll('.pdf-search-match').length === 5)
  const firstBox = await page.locator('.pdf-search-match.is-current').first().evaluate(node => ({ left: parseFloat(node.style.left), width: parseFloat(node.style.width), top: parseFloat(node.style.top) }))
  await next.click(); await waitCount('2 / 6')
  const secondBox = await page.locator('.pdf-search-match.is-current').first().evaluate(node => ({ left: parseFloat(node.style.left), width: parseFloat(node.style.width) }))
  assert.ok(secondBox.left > firstBox.left && secondBox.width < 100)
  await search.press('Shift+Enter'); await waitCount('1 / 6'); await search.press('Shift+Enter'); await waitCount('6 / 6')
  await waitActive(fixture.model.pages[1].pageId)
  await search.press('Enter'); await waitCount('1 / 6')
  await page.locator('[data-source-command-id="genoffice.pdf.search.wholeWord"]').click(); await waitCount('1 / 4')
  await page.locator('[data-source-command-id="genoffice.pdf.search.matchCase"]').click(); await waitCount('1 / 3')
  await search.fill('invoice'); await waitCount('1 / 1'); await waitActive(fixture.model.pages[1].pageId)
  await search.fill('missing'); await waitCount('无匹配；扫描页需 OCR'); assert.equal(await next.isDisabled(), true)
  await search.fill('cat'); await waitCount('1 / 3'); await search.press('Escape'); await waitCount('')
  await page.locator('[data-pdf-ribbon-tab="view"]').click(); await page.locator('[data-source-command-id="genoffice.pdf.view.navigation.search"]').click()
  assert.equal(await search.evaluate(node => node === document.activeElement), true)
  await page.locator('[data-pdf-ribbon-tab="page"]').click(); await page.keyboard.press('Control+f'); assert.equal(await search.evaluate(node => node === document.activeElement), true)
  assert.deepEqual(await ops(), beforeDraft)
  await page.locator('[data-source-command-id="genoffice.pdf.search.wholeWord"]').click(); await page.locator('[data-source-command-id="genoffice.pdf.search.matchCase"]').click()
  await search.fill('cat'); await waitCount('1 / 6')
  await page.locator('[data-pdf-ribbon-tab="page"]').click(); await page.locator('[data-source-command-id="genoffice.pdf.page.delete"]').click(); await waitCount('1 / 1')
  await page.locator('[data-pdf-ribbon-tab="home"]').click(); await page.getByRole('button', { name: /^(撤销|Undo)$/ }).click(); await waitCount('1 / 6')
  await page.locator('[data-pdf-ribbon-tab="page"]').click(); await page.locator('[data-source-command-id="genoffice.pdf.page.reverse"]').click()
  await page.locator('[data-pdf-ribbon-tab="home"]').click()
  const jump = page.locator('[data-source-command-id="genoffice.pdf.home.pageZoom.goToPage"]'); await jump.fill('3'); await jump.press('Enter')
  await page.waitForFunction(() => [...document.querySelectorAll('.textLayer span')].some(node => node.textContent === 'cat cat scatter CAT cat_'))
  await page.evaluate(() => { const node = [...document.querySelectorAll('.textLayer span')].find(node => node.textContent === 'cat cat scatter CAT cat_'); const range = document.createRange(); range.selectNodeContents(node); const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range); document.dispatchEvent(new Event('selectionchange')) })
  await page.locator('[data-source-command-id="genoffice.pdf.home.markup.underline"]').click()
  await page.locator('[data-pdf-ribbon-tab="edit"]').click(); await page.getByRole('button', { name: '校验当前修改', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('.native-pdf-editor')?.dataset.pdfPreview === 'true', null, { timeout: 30000 })
  await page.keyboard.press('Control+f'); await search.fill('invoice'); await waitCount('1 / 1'); await waitActive(fixture.model.pages[1].pageId)
  await search.fill('cat'); await waitCount('1 / 6'); await waitActive(fixture.model.pages[1].pageId)
  await page.locator('[data-pdf-ribbon-tab="edit"]').click(); await page.getByRole('button', { name: '返回原稿编辑', exact: true }).click(); await waitCount('1 / 6')
  await page.evaluate(() => localStorage.clear()); readonly = true; await open(); await search.fill('cat'); await waitCount('1 / 6'); await next.click(); await waitCount('2 / 6')
  assert.ok((await ops()).every(ops => !ops.length))
  const downloaded = Buffer.from(await page.evaluate(async () => [...new Uint8Array(await (await fetch('/reports/v1/native/search-fixture/1/api/file')).arrayBuffer())])); assert.equal(sha(downloaded), sha(source)); assert.deepEqual(errors, [])
  const evidence = { ok: true, browserVersion: browser.version(), sourceSha256: sha(source), downloadedSha256: sha(downloaded), firstBox, secondBox, perOccurrenceAndWrap: true, caseAndWholeWord: true, originalPageIdentityAfterDeleteUndoReorderAndPreview: true, readonlyAndDraftInvariant: true, previewSha256: sha(previewBytes), provenance: 'production static UI; substituted auth/revision routes; real packed engine and PDF.js rendering; no desktop or production acceptance' }
  if (process.env.PDF_SEARCH_EVIDENCE_DIR) { const dir = process.env.PDF_SEARCH_EVIDENCE_DIR; await mkdir(dir, { recursive: true }); await writeFile(`${dir}/source.pdf`, source); await writeFile(`${dir}/preview.pdf`, previewBytes); await writeFile(`${dir}/evidence.json`, JSON.stringify(evidence, null, 2)); await page.screenshot({ path: `${dir}/search.png`, fullPage: true }) }
  console.log(JSON.stringify(evidence))
} finally { await browser?.close(); server.kill('SIGTERM') }
