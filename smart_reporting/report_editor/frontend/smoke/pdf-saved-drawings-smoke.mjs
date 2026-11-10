import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.PDF_SAVED_DRAWINGS_SMOKE_PORT ?? 4212), base = `http://127.0.0.1:${port}`, sha = bytes => createHash('sha256').update(bytes).digest('hex')
function python(input) {
  const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import json,sys,base64
from io import BytesIO
from pypdf import PdfReader,PdfWriter
from smart_reporting.reporting.tests.test_pdf_page_size import size_fixture
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf,patch_pdf,patch_pdf_with_receipt
p=json.load(sys.stdin)
if p['mode']=='create':
 b=size_fixture();page=inspect_pdf(b)['pages'][0];b=patch_pdf(b,[{'kind':'addDrawing','pageId':page['pageId'],'shape':'arrow','from':[80,120],'to':[180,180],'color':[1,0,0],'width':2} for _ in range(2)]);print(json.dumps({'bytes':base64.b64encode(b).decode(),'model':inspect_pdf(b)}))
elif p['mode']=='verify':
 a=PdfReader(BytesIO(base64.b64decode(p['source'])));b=PdfReader(BytesIO(base64.b64decode(p['bytes'])))
 assert len(a.pages)==len(b.pages)==3
 assert [page.extract_text() for page in a.pages]==[page.extract_text() for page in b.pages]
 fields=lambda reader:{name:{key:str(field.get(key)) for key in ['/FT','/T','/V','/DV','/Ff','/Opt']} for name,field in (reader.get_fields() or {}).items()}
 assert fields(a)==fields(b)
 before=[ref.get_object() for ref in a.pages[0]['/Annots']];after=[ref.get_object() for ref in b.pages[0]['/Annots']]
 assert sum(x.get('/Subtype')=='/Line' for x in before)==2
 assert sum(x.get('/Subtype')=='/Line' for x in after)==1
 assert len(before)==len(after)+1
 print(json.dumps({'pages':len(b.pages),'remainingLines':1,'textAndFieldsPreserved':True}))
elif p['mode']=='inspect':print(json.dumps(inspect_pdf(base64.b64decode(p['bytes']))))
elif p['mode']=='patch':
 b=base64.b64decode(p['bytes']);r=patch_pdf_with_receipt(b,p['operations']);r['bytes']=base64.b64encode(r.pop('content')).decode();r['model']=inspect_pdf(base64.b64decode(r['bytes']));print(json.dumps(r))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw Error(result.stderr)
  return JSON.parse(result.stdout)
}
const fixture = python({ mode: 'create' }), source = Buffer.from(fixture.bytes, 'base64'), revisions = new Map([[1, source]]), payloads = []
let browser, readonly = false
const server = spawn('./node_modules/.bin/vite', ['preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
try {
  for (let n = 0; n < 100; n++) { try { if ((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true, executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ?? '/usr/bin/chromium' })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } }), errors = []
  page.on('pageerror', error => errors.push(error.message)); page.on('console', entry => { if (entry.type() === 'error') errors.push(entry.text()) })
  const revision = route => Number(route.request().url().match(/drawings-fixture\/(\d+)\/api/)[1]), active = route => revisions.get(revision(route))
  const inspect = bytes => python({ mode: 'inspect', bytes: bytes.toString('base64') }), patch = (bytes, operations) => python({ mode: 'patch', bytes: bytes.toString('base64'), operations })
  await page.route('**/reports/v1/native/drawings-fixture/*/api/context', route => route.fulfill({ json: {
    context: { documentId: 'drawings-fixture', revision: revision(route), parentRevision: revision(route) === 1 ? null : revision(route) - 1, format: 'pdf', origin: 'upload', scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' }, sourceFile: { path: 'drawings.pdf', size: active(route).length, sha256: sha(active(route)), mediaType: 'application/pdf' } }, csrfToken: 'fixture', capabilities: { pdf_editor: true }, editingEnabled: !readonly,
  } }))
  await page.route('**/reports/v1/native/drawings-fixture/*/api/file', route => route.fulfill({ body: active(route), contentType: 'application/pdf' }))
  await page.route('**/reports/v1/native/drawings-fixture/*/api/preview', route => {
    const bytes = active(route), ops = route.request().postDataJSON().operations, result = ops.length ? patch(bytes, ops) : null
    return route.fulfill({ json: { sourceSha256: sha(bytes), model: result?.model ?? inspect(bytes), appliedOperationIndices: result?.appliedOperationIndices ?? [], skippedOperations: [], previewDigest: result?.previewDigest } })
  })
  await page.route('**/reports/v1/native/drawings-fixture/*/api/preview.pdf', route => {
    const input = route.request().postDataJSON(), result = patch(active(route), input.operations); assert.equal(input.expectedPreviewDigest, result.previewDigest)
    return route.fulfill({ body: Buffer.from(result.bytes, 'base64'), contentType: 'application/pdf', headers: { 'X-Native-Preview-Digest': result.previewDigest } })
  })
  await page.route('**/reports/v1/native/drawings-fixture/*/api/save', route => {
    const input = route.request().postDataJSON(), result = patch(active(route), input.operations), next = revision(route) + 1, bytes = Buffer.from(result.bytes, 'base64'); payloads.push(input); revisions.set(next, bytes)
    return route.fulfill({ json: { documentId: 'drawings-fixture', revision: next, parentRevision: next - 1, revisionRegistered: true, artifacts: { pdf: { downloadUrl: `/drawing-download-${next}.pdf`, size: bytes.length, sha256: sha(bytes) } }, editor: { openUrl: `/reports/v1/native/drawings-fixture/${next}` }, validation: { ok: false, issues: [{ code: 'manual_review', message: '请核验内容；下载仍可用' }] } } })
  })
  await page.route(/\/drawing-download-\d+\.pdf$/, route => route.fulfill({ body: revisions.get(Number(route.request().url().match(/drawing-download-(\d+)/)[1])), contentType: 'application/pdf' }))
  await page.route(/\/reports\/v1\/native\/drawings-fixture\/[123]$/, async route => route.fulfill({ response: await route.fetch({ url: `${base}/reports/v1/editor/assets/native.html` }) }))
  const open = async n => { await page.goto(`${base}/reports/v1/native/drawings-fixture/${n}`); await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 3 && document.querySelector('.pdf-page canvas'), null, { timeout: 60000 }) }
  const ops = () => page.evaluate(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.includes('drawings-fixture'))?.[1] ?? '{"operations":[]}').operations)
  const panel = page.locator('.pdf-saved-drawings'), rows = panel.locator('[data-pdf-saved-drawing]')
  const show = async () => { await page.locator('[data-pdf-ribbon-tab="annotate"]').click(); await page.getByRole('button', { name: '已保存绘图', exact: true }).click() }
  const preview = async () => { await page.locator('[data-pdf-ribbon-tab="edit"]').click(); await page.getByRole('button', { name: '校验当前修改', exact: true }).click(); await page.waitForFunction(() => document.querySelector('.native-pdf-editor')?.dataset.pdfPreview === 'true', null, { timeout: 30000 }); await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 3 && document.querySelector('.pdf-page canvas')) }
  const save = async n => { await page.locator('[data-action="save"]').click(); await page.waitForFunction(n => document.querySelector('.save-state-label')?.textContent === `已保存修订 ${n}`, n, { timeout: 30000 }); const link = await page.locator('.native-delivery a').filter({ hasText: '下载 PDF' }).getAttribute('href'); const bytes = Buffer.from(await page.evaluate(async url => [...new Uint8Array(await (await fetch(url)).arrayBuffer())], link)); assert.deepEqual(bytes, revisions.get(n)) }
  await open(1); await show(); assert.equal(await rows.count(), 2)
  const first = fixture.model.pages[0].drawings[0], second = fixture.model.pages[0].drawings[1]
  assert.deepEqual(first.rect, second.rect); assert.notEqual(first.annotationId, second.annotationId)
  await rows.last().getByRole('button', { name: '暂存删除' }).click()
  assert.equal((await ops())[0].annotationId, second.annotationId)
  await rows.last().getByRole('button', { name: '撤销此删除' }).click(); assert.deepEqual(await ops(), [])
  await rows.last().getByRole('button', { name: '暂存删除' }).click(); const pending = await ops()
  await page.locator('[data-pdf-ribbon-tab="home"]').click()
  await page.getByRole('button', { name: /^(撤销|Undo)$/ }).click(); assert.deepEqual(await ops(), [])
  await page.getByRole('button', { name: /^(重做|Redo)$/ }).click(); assert.deepEqual(await ops(), pending)
  await page.reload(); await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 3); assert.deepEqual(await ops(), pending)
  await show(); await preview(); assert.equal(await rows.last().getByRole('button').isDisabled(), true)
  await save(2); const saved = inspect(revisions.get(2)); assert.equal(saved.pages[0].drawings.length, 1)
  assert.deepEqual(saved.pages[0].notes.map(note => note.contents), fixture.model.pages[0].notes.map(note => note.contents))
  assert.equal(saved.pages[0].drawings[0].expectedAnnotationSha256, first.expectedAnnotationSha256)
  const independent = python({ mode: 'verify', source: fixture.bytes, bytes: revisions.get(2).toString('base64') })
  await open(2); await show(); assert.equal(await rows.count(), 1)
  readonly = true; await open(2); await show(); assert.equal(await rows.first().getByRole('button').isDisabled(), true)
  assert.deepEqual(await ops(), []); assert.deepEqual(errors, [])
  const evidence = { ok: true, independent, browserVersion: browser.version(), revisions: [...revisions].map(([revision, bytes]) => ({ revision, sha256: sha(bytes), size: bytes.length })), operations: payloads.map(input => input.operations), exactTwinIdentityAndCancelRestoreUndoRedoReload: true, previewAndActualDownloads: true, readonlyAndPreviewControls: true, provenance: 'production static UI; substituted authorization/revision routes; actual packed engine, PDF.js and downloads; no desktop/full-image/production acceptance' }
  if (process.env.PDF_SAVED_DRAWINGS_EVIDENCE_DIR) { const dir = process.env.PDF_SAVED_DRAWINGS_EVIDENCE_DIR; await mkdir(dir, { recursive: true }); for (const [n, bytes] of revisions) await writeFile(`${dir}/revision-${n}.pdf`, bytes); await writeFile(`${dir}/evidence.json`, JSON.stringify(evidence, null, 2)); await page.screenshot({ path: `${dir}/readonly-reopen.png`, fullPage: true }) }
  console.log(JSON.stringify(evidence))
} finally { await browser?.close(); server.kill('SIGTERM') }
