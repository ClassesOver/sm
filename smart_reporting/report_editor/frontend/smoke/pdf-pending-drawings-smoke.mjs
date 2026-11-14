import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { observePdfBuiltAssets, inspectPdfObjectDialog } from './pdf-object-dialog-checks.mjs'
import { inspectPdfObjectPanel } from './pdf-object-panel-checks.mjs'
import { inspectPdfDrawingKeys } from './pdf-gesture-keyboard-checks.mjs'
const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.PDF_PENDING_DRAWINGS_SMOKE_PORT ?? 4213), base = `http://127.0.0.1:${port}`, sha = bytes => createHash('sha256').update(bytes).digest('hex')
function python(input) {
  const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import json,sys,base64
from io import BytesIO
from pypdf import PdfReader,PdfWriter
from pypdf.generic import ContentStream
from math import isclose
from smart_reporting.reporting.tests.test_pdf_page_size import size_fixture
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf,patch_pdf,patch_pdf_with_receipt
p=json.load(sys.stdin)
if p['mode']=='create':
 b=size_fixture();print(json.dumps({'bytes':base64.b64encode(b).decode(),'model':inspect_pdf(b)}))
elif p['mode']=='verify':
 a=PdfReader(BytesIO(base64.b64decode(p['source'])));b=PdfReader(BytesIO(base64.b64decode(p['bytes'])))
 assert len(a.pages)==len(b.pages)==3
 assert [page.extract_text() for page in b.pages]==[page.extract_text() for page in reversed(a.pages)]
 fields=lambda reader:{name:{key:str(field.get(key)) for key in ['/FT','/T','/V','/DV','/Ff','/Opt']} for name,field in (reader.get_fields() or {}).items()}
 assert fields(a)==fields(b)
 saved=b.pages[2];assert saved.get('/Rotate',0)==90
 squares=[ref.get_object() for ref in saved['/Annots'] if ref.get_object().get('/Subtype')=='/Square']
 assert len(squares)==1
 shape=p['rect'];pad=float(squares[0]['/BS']['/W'])+2
 expected=[shape[0]-pad,shape[1]-pad,shape[2]+pad,shape[3]+pad]
 assert all(isclose(float(actual),value,abs_tol=1e-7) for actual,value in zip(squares[0]['/Rect'],expected,strict=True))
 drawn=[operands for operands,operator in ContentStream(squares[0]['/AP']['/N'].get_object(),b).operations if operator==b're']
 assert len(drawn)==1
 assert all(isclose(float(actual),round(value,2),abs_tol=1e-7) for actual,value in zip(drawn[0],[shape[0],shape[1],shape[2]-shape[0],shape[3]-shape[1]],strict=True))
 assert len(a.pages[0].get('/Annots',[]))+1==len(saved['/Annots'])
 print(json.dumps({'pages':len(b.pages),'remainingSquares':1,'rect':p['rect'],'textAndFieldsPreserved':True,'sourceRotationAndReorder':True}))
elif p['mode']=='inspect':print(json.dumps(inspect_pdf(base64.b64decode(p['bytes']))))
elif p['mode']=='patch':
 b=base64.b64decode(p['bytes']);r=patch_pdf_with_receipt(b,p['operations']);r['bytes']=base64.b64encode(r.pop('content')).decode();r['model']=inspect_pdf(base64.b64decode(r['bytes']));print(json.dumps(r))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw Error(result.stderr)
  return JSON.parse(result.stdout)
}
const fixture = python({ mode: 'create' }), source = Buffer.from(fixture.bytes, 'base64'), revisions = new Map([[1, source]]), payloads = []
let browser, readonly = false
const server = spawn('./node_modules/.bin/vite', ['preview', ...(process.env.PDF_SMOKE_VITE_CONFIG?['--config',process.env.PDF_SMOKE_VITE_CONFIG]:[]), '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
try {
  for (let n = 0; n < 100; n++) { try { if ((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? {executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE} : {}) })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } }), errors = []
  const verifyAssets=await observePdfBuiltAssets(page)
  page.on('pageerror', error => errors.push(error.message)); page.on('console', entry => { if (entry.type() === 'error') errors.push(entry.text()) })
  const revision = route => Number(route.request().url().match(/pending-drawings-fixture\/(\d+)\/api/)[1]), active = route => revisions.get(revision(route))
  const inspect = bytes => python({ mode: 'inspect', bytes: bytes.toString('base64') }), patch = (bytes, operations) => python({ mode: 'patch', bytes: bytes.toString('base64'), operations })
  await page.route('**/reports/v1/native/pending-drawings-fixture/*/api/context', route => route.fulfill({ json: {
    context: { documentId: 'pending-drawings-fixture', revision: revision(route), parentRevision: revision(route) === 1 ? null : revision(route) - 1, format: 'pdf', origin: 'upload', scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' }, sourceFile: { path: 'drawings.pdf', size: active(route).length, sha256: sha(active(route)), mediaType: 'application/pdf' } }, csrfToken: 'fixture', capabilities: { pdf_editor: true }, editingEnabled: !readonly,
  } }))
  await page.route('**/reports/v1/native/pending-drawings-fixture/*/api/file', route => route.fulfill({ body: active(route), contentType: 'application/pdf' }))
  await page.route('**/reports/v1/native/pending-drawings-fixture/*/api/preview', route => {
    const bytes = active(route), ops = route.request().postDataJSON().operations, result = ops.length ? patch(bytes, ops) : null
    return route.fulfill({ json: { sourceSha256: sha(bytes), model: result?.model ?? inspect(bytes), appliedOperationIndices: result?.appliedOperationIndices ?? [], skippedOperations: [], previewDigest: result?.previewDigest } })
  })
  await page.route('**/reports/v1/native/pending-drawings-fixture/*/api/preview.pdf', route => {
    const input = route.request().postDataJSON(), result = patch(active(route), input.operations); assert.equal(input.expectedPreviewDigest, result.previewDigest)
    return route.fulfill({ body: Buffer.from(result.bytes, 'base64'), contentType: 'application/pdf', headers: { 'X-Native-Preview-Digest': result.previewDigest } })
  })
  await page.route('**/reports/v1/native/pending-drawings-fixture/*/api/save', route => {
    const input = route.request().postDataJSON(), result = patch(active(route), input.operations), next = revision(route) + 1, bytes = Buffer.from(result.bytes, 'base64'); payloads.push(input); revisions.set(next, bytes)
    return route.fulfill({ json: { documentId: 'pending-drawings-fixture', revision: next, parentRevision: next - 1, revisionRegistered: true, artifacts: { pdf: { downloadUrl: `/drawing-download-${next}.pdf`, size: bytes.length, sha256: sha(bytes) } }, editor: { openUrl: `/reports/v1/native/pending-drawings-fixture/${next}` }, validation: { ok: false, issues: [{ code: 'manual_review', message: '请核验内容；下载仍可用' }] } } })
  })
  await page.route(/\/drawing-download-\d+\.pdf$/, route => route.fulfill({ body: revisions.get(Number(route.request().url().match(/drawing-download-(\d+)/)[1])), contentType: 'application/pdf' }))
  await page.route(/\/reports\/v1\/native\/pending-drawings-fixture\/[123]$/, async route => route.fulfill({ response: await route.fetch({ url: `${base}/reports/v1/editor/assets/native.html` }) }))
  const open = async n => { await page.goto(`${base}/reports/v1/native/pending-drawings-fixture/${n}`); await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 3 && document.querySelector('.pdf-page canvas'), null, { timeout: 60000 }) }
  const ops = () => page.evaluate(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.includes('pending-drawings-fixture'))?.[1] ?? '{"operations":[]}').operations)
  const panel = page.locator('.pdf-pending-drawings-panel'), rows = panel.locator('[data-pdf-pending-drawing]')
  const show = async () => { await page.locator('[data-pdf-ribbon-tab="annotate"]').click(); await page.getByRole('button', { name: '待保存绘图', exact: true }).click() }
  const loaded = () => page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 3 && document.querySelector('.pdf-page canvas'), null, { timeout: 60000 })
  const preview = async () => { await page.locator('[data-pdf-ribbon-tab="edit"]').click(); await page.getByRole('button', { name: '校验当前修改', exact: true }).click(); await page.waitForFunction(() => document.querySelector('.native-pdf-editor')?.dataset.pdfPreview === 'true', null, { timeout: 30000 }); await loaded() }
  const save = async n => {
    const confirmation=page.locator('.pdf-preview-review input[type=checkbox]');if(await confirmation.isVisible())await confirmation.check()
    await page.locator('[data-action="save"]').click(); await page.waitForFunction(n => document.querySelector('.save-state-label')?.textContent === `已保存修订 ${n}`, n, { timeout: 30000 })
    const link=page.locator('.native-delivery a').filter({hasText:'下载 PDF'}),downloading=page.waitForEvent('download');await link.click();const download=await downloading;assert.equal(await download.failure(),null)
    const {readFile}=await import('node:fs/promises'),bytes=await readFile(await download.path());assert.deepEqual(bytes,revisions.get(n));assert.equal(await page.locator('.native-delivery').getByText('请核验内容；下载仍可用',{exact:true}).count(),1)
  }
  await open(1)
  await page.locator('[data-pdf-ribbon-tab="annotate"]').click()
  await page.locator('[data-pdf-draw-shape="rect"]').click()
  const content = page.locator('.pdf-page').first().locator('.pdf-page-content')
  const drag = async () => {
    await content.scrollIntoViewIfNeeded(); const box = await content.boundingBox()
    await page.mouse.move(box.x + box.width * .2, box.y + box.height * .3); await page.mouse.down()
    await page.mouse.move(box.x + box.width * .4, box.y + box.height * .45, { steps: 4 }); await page.mouse.up(); await loaded()
  }
  await drag(); await page.waitForFunction(() => document.querySelectorAll('[data-pdf-drawing="rect"]').length === 1)
  await drag(); await page.waitForFunction(() => document.querySelectorAll('[data-pdf-drawing="rect"]').length === 2)
  const twins = await ops(); assert.equal(twins.length, 2); assert.deepEqual(twins[0], twins[1])
  const gestureKeyboard=process.env.PDF_GESTURE_KEYBOARD==='1'?await inspectPdfDrawingKeys(page,{operations:ops,loaded,directory:process.env.PDF_PENDING_DRAWINGS_EVIDENCE_DIR}):[]
  await page.locator('[data-pdf-ribbon-tab="page"]').click()
  await page.locator('[data-source-command-id="genoffice.pdf.page.rotateRight"]').click(); await loaded()
  await page.locator('[data-source-command-id="genoffice.pdf.page.reverse"]').click(); await loaded()
  await show(); assert.equal(await rows.count(), 2)
  const original = await ops()
  await rows.first().getByRole('button').evaluate(node => { window.__oldPendingSelect = node })
  await rows.last().getByRole('button', { name: '选择此绘图' }).click()
  assert.match(await panel.innerText(), /已选择草稿操作 #2/)
  await page.evaluate(() => window.__oldPendingSelect.click())
  assert.match(await panel.innerText(), /已选择草稿操作 #2/)
  const dialog = page.getByRole('dialog', { name: '移动待保存绘图', exact: true })
  const objectPanels=await inspectPdfObjectPanel(page,{panel,kind:'drawings',operations:ops,directory:process.env.PDF_PENDING_DRAWINGS_EVIDENCE_DIR})
  const objectLayouts=await inspectPdfObjectDialog(page,{opener:panel.getByRole('button',{name:'移动所选绘图',exact:true}),title:'移动待保存绘图',operations:ops,directory:process.env.PDF_PENDING_DRAWINGS_EVIDENCE_DIR})
  await panel.getByRole('button', { name: '移动所选绘图', exact: true }).click()
  await dialog.locator('form').evaluate(node => { window.__cancelledPendingMove = node })
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  await page.evaluate(() => window.__cancelledPendingMove.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
  assert.deepEqual(await ops(), original)
  await panel.getByRole('button', { name: '移动所选绘图', exact: true }).click()
  await dialog.locator('form').evaluate(node => { window.__replacedPendingMove = node })
  await panel.getByRole('button', { name: '移动所选绘图', exact: true }).evaluate(node => node.click())
  await page.evaluate(() => window.__replacedPendingMove.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
  assert.deepEqual(await ops(), original)
  assert.equal(await page.locator('.pdf-pending-drawing-dialog[open]').count(), 1)
  await dialog.getByLabel('X 位移（PDF 单位）', { exact: true }).fill('9999')
  await dialog.getByRole('button', { name: '应用位移', exact: true }).click()
  assert.match(await dialog.getByRole('alert').innerText(), /页面内/); assert.deepEqual(await ops(), original)
  // Deliberately dispatch an underlying history command to simulate an obsolete modal callback.
  await page.locator('[data-pdf-ribbon-tab="home"]').evaluate(node => node.click())
  await page.getByRole('button', { name: /^(撤销|Undo)$/ }).evaluate(node => node.click()); await loaded()
  const staleSnapshot = await ops()
  await dialog.getByLabel('X 位移（PDF 单位）', { exact: true }).fill('10')
  await dialog.getByRole('button', { name: '应用位移', exact: true }).click()
  assert.match(await dialog.getByRole('alert').innerText(), /已变化/); assert.deepEqual(await ops(), staleSnapshot)
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  await page.getByRole('button', { name: /^(重做|Redo)$/ }).click(); await loaded(); assert.deepEqual(await ops(), original)
  await rows.last().getByRole('button', { name: '选择此绘图' }).click()
  await panel.getByRole('button', { name: '移动所选绘图', exact: true }).click()
  await dialog.getByLabel('X 位移（PDF 单位）', { exact: true }).fill('10')
  await dialog.getByLabel('Y 位移（PDF 单位）', { exact: true }).fill('15')
  await dialog.getByRole('button', { name: '应用位移', exact: true }).click(); await loaded()
  const moved = await ops(), expectedRect = original[1].rect.map((value, index) => value + (index % 2 ? 15 : 10))
  assert.deepEqual(moved[0], original[0]); assert.deepEqual(moved[1], { ...original[1], rect: expectedRect }); assert.deepEqual(moved.slice(2), original.slice(2))
  await page.getByRole('button', { name: /^(撤销|Undo)$/ }).click(); await loaded(); assert.deepEqual(await ops(), original)
  await page.getByRole('button', { name: /^(重做|Redo)$/ }).click(); await loaded(); assert.deepEqual(await ops(), moved)
  await page.reload(); await loaded(); assert.deepEqual(await ops(), moved); await page.locator('.pdf-page-label').last().click(); await show()
  await rows.first().getByRole('button', { name: '选择此绘图' }).click()
  await panel.getByRole('button', { name: '删除所选绘图', exact: true }).click(); await loaded()
  const final = await ops(); assert.deepEqual(final, moved.slice(1)); assert.equal(await rows.count(), 1)
  await preview(); assert.equal(await rows.first().getByRole('button').isDisabled(), true)
  await save(2)
  if (process.env.PDF_PENDING_DRAWINGS_EVIDENCE_DIR) { const dir = process.env.PDF_PENDING_DRAWINGS_EVIDENCE_DIR; await mkdir(dir, { recursive: true }); await writeFile(`${dir}/actual-download.pdf`, revisions.get(2)); await writeFile(`${dir}/source.pdf`, source); await writeFile(`${dir}/saved-operations.json`, JSON.stringify(payloads[0].operations, null, 2)) }
  const independent = python({ mode: 'verify', source: fixture.bytes, bytes: revisions.get(2).toString('base64'), rect: expectedRect })
  await open(2); await show(); assert.equal(await rows.count(), 0)
  await page.getByRole('button', { name: '已保存绘图', exact: true }).click()
  assert.equal(await page.locator('[data-pdf-saved-drawing]').count(), 0) // active source page now refers to the original last page
  await page.locator('.pdf-page-label').last().click()
  assert.equal(await page.locator('[data-pdf-saved-drawing]').count(), 1)
  readonly = true; await open(1); await page.locator('[data-pdf-ribbon-tab="annotate"]').click()
  await page.locator('[data-pdf-draw-shape="rect"]').evaluate(node => node.click())
  await drag(); assert.deepEqual(await ops(), [])
  assert.deepEqual(errors, [])
  const evidence = { ok: true, ...await verifyAssets(), objectLayouts, independent, browserVersion: browser.version(), revisions: [...revisions].map(([revision, bytes]) => ({ revision, sha256: sha(bytes), size: bytes.length })), operations: payloads.map(input => input.operations), exactTwinSelectionMoveDelete: true, stalePaneAndCancelledReplacedStaleModalRefused: true, undoRedoReload: true, rotatedAndReorderedSource: true, previewActualDownloadReopen: true, readonlyIsolation: true, provenance: 'production static Web list/modal adaptation; substituted authorization/revision routes; actual packed engine, PDF.js and downloads; no desktop drag/full-image/production acceptance' }
  evidence.objectPanels=objectPanels;evidence.gestureKeyboard=gestureKeyboard
  if (process.env.PDF_PENDING_DRAWINGS_EVIDENCE_DIR) { const dir = process.env.PDF_PENDING_DRAWINGS_EVIDENCE_DIR; await mkdir(dir, { recursive: true }); for (const [n, bytes] of revisions) await writeFile(`${dir}/revision-${n}.pdf`, bytes); await writeFile(`${dir}/evidence.json`, JSON.stringify(evidence, null, 2)); await page.screenshot({ path: `${dir}/readonly-reopen.png`, fullPage: true }) }
  console.log(JSON.stringify(evidence))
} catch(error){const dir=process.env.PDF_PENDING_DRAWINGS_EVIDENCE_DIR;if(dir&&browser){await mkdir(dir,{recursive:true});const page=browser.contexts()[0]?.pages()[0];if(page){await page.screenshot({path:`${dir}/failure.png`,fullPage:true});await writeFile(`${dir}/failure.json`,JSON.stringify({error:String(error),payloads,state:await page.evaluate(()=>({text:document.body.innerText,operations:Object.entries(localStorage).filter(([key])=>key.includes('pending-drawings-fixture'))}))},null,2))}}throw error
} finally { await browser?.close(); server.kill('SIGTERM') }
