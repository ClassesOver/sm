import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.PDF_IMAGE_RESIZE_SMOKE_PORT ?? 4215), base = `http://127.0.0.1:${port}`, sha = bytes => createHash('sha256').update(bytes).digest('hex')
function python(input) {
  const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import json,sys,base64
from io import BytesIO
from pypdf import PdfReader,PdfWriter
from pypdf.generic import ContentStream
from math import isclose
from PIL import Image
from hashlib import sha256
from smart_reporting.reporting.tests.test_pdf_page_size import size_fixture
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf,patch_pdf,patch_pdf_with_receipt
p=json.load(sys.stdin)
if p['mode']=='create':
 b=size_fixture();image=Image.new('RGB',(4,2));image.putdata([(255,0,0),(0,255,0),(0,0,255),(255,255,0)]*2);png=BytesIO();image.save(png,format='PNG');print(json.dumps({'bytes':base64.b64encode(b).decode(),'model':inspect_pdf(b),'image':base64.b64encode(png.getvalue()).decode(),'imagePixelsSha256':sha256(image.tobytes()).hexdigest()}))
elif p['mode']=='verify':
 a=PdfReader(BytesIO(base64.b64decode(p['source'])));b=PdfReader(BytesIO(base64.b64decode(p['bytes'])))
 assert len(a.pages)==len(b.pages)==3
 assert [page.extract_text() for page in b.pages]==[page.extract_text() for page in reversed(a.pages)]
 fields=lambda reader:{name:{key:str(field.get(key)) for key in ['/FT','/T','/V','/DV','/Ff','/Opt']} for name,field in (reader.get_fields() or {}).items()}
 assert fields(a)==fields(b)
 saved=b.pages[2];assert saved.get('/Rotate',0)==90
 stamps=[ref.get_object() for ref in saved['/Annots'] if ref.get_object().get('/Subtype')=='/Stamp']
 assert len(stamps)==2
 shapes=p['rects'];pixels=[]
 for annot,shape in zip(stamps,shapes,strict=True):
  assert all(isclose(float(actual),round(value,2),abs_tol=1e-7) for actual,value in zip(annot['/Rect'],shape,strict=True))
  ap=annot['/AP']['/N'].get_object();w,h=shape[2]-shape[0],shape[3]-shape[1]
  assert all(isclose(float(actual),round(value,2),abs_tol=1e-7) for actual,value in zip(ap['/BBox'],[0,0,w,h],strict=True))
  matrices=[operands for operands,operator in ContentStream(ap,b).operations if operator==b'cm']
  assert len(matrices)==1
  assert all(isclose(float(actual),round(value,2),abs_tol=1e-7) for actual,value in zip(matrices[0],[0,h,-w,0,w,0],strict=True))
  image=ap['/Resources']['/XObject']['/Im0'].get_object()
  assert image['/Width']==4 and image['/Height']==2 and str(image['/ColorSpace'])=='/DeviceRGB'
  pixels.append(sha256(image.get_data()).hexdigest())
 assert pixels==[p['imagePixelsSha256']]*2
 assert len(a.pages[0].get('/Annots',[]))+2==len(saved['/Annots'])
 print(json.dumps({'pages':len(b.pages),'imageStamps':2,'rects':shapes,'imagePixelsSha256':pixels[0],'imageBytesAndAspectPreserved':True,'textAndFieldsPreserved':True,'sourceRotationAndReorder':True}))
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
  const revision = route => Number(route.request().url().match(/image-resize-fixture\/(\d+)\/api/)[1]), active = route => revisions.get(revision(route))
  const inspect = bytes => python({ mode: 'inspect', bytes: bytes.toString('base64') }), patch = (bytes, operations) => python({ mode: 'patch', bytes: bytes.toString('base64'), operations })
  await page.route('**/reports/v1/native/image-resize-fixture/*/api/context', route => route.fulfill({ json: {
    context: { documentId: 'image-resize-fixture', revision: revision(route), parentRevision: revision(route) === 1 ? null : revision(route) - 1, format: 'pdf', origin: 'upload', scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' }, sourceFile: { path: 'drawings.pdf', size: active(route).length, sha256: sha(active(route)), mediaType: 'application/pdf' } }, csrfToken: 'fixture', capabilities: { pdf_editor: true }, editingEnabled: !readonly,
  } }))
  await page.route('**/reports/v1/native/image-resize-fixture/*/api/file', route => route.fulfill({ body: active(route), contentType: 'application/pdf' }))
  await page.route('**/reports/v1/native/image-resize-fixture/*/api/preview', route => {
    const bytes = active(route), ops = route.request().postDataJSON().operations, result = ops.length ? patch(bytes, ops) : null
    return route.fulfill({ json: { sourceSha256: sha(bytes), model: result?.model ?? inspect(bytes), appliedOperationIndices: result?.appliedOperationIndices ?? [], skippedOperations: [], previewDigest: result?.previewDigest } })
  })
  await page.route('**/reports/v1/native/image-resize-fixture/*/api/preview.pdf', route => {
    const input = route.request().postDataJSON(), result = patch(active(route), input.operations); assert.equal(input.expectedPreviewDigest, result.previewDigest)
    return route.fulfill({ body: Buffer.from(result.bytes, 'base64'), contentType: 'application/pdf', headers: { 'X-Native-Preview-Digest': result.previewDigest } })
  })
  await page.route('**/reports/v1/native/image-resize-fixture/*/api/save', route => {
    const input = route.request().postDataJSON(), result = patch(active(route), input.operations), next = revision(route) + 1, bytes = Buffer.from(result.bytes, 'base64'); payloads.push(input); revisions.set(next, bytes)
    return route.fulfill({ json: { documentId: 'image-resize-fixture', revision: next, parentRevision: next - 1, revisionRegistered: true, artifacts: { pdf: { downloadUrl: `/drawing-download-${next}.pdf`, size: bytes.length, sha256: sha(bytes) } }, editor: { openUrl: `/reports/v1/native/image-resize-fixture/${next}` }, validation: { ok: false, issues: [{ code: 'manual_review', message: '请核验内容；下载仍可用' }] } } })
  })
  await page.route(/\/drawing-download-\d+\.pdf$/, route => route.fulfill({ body: revisions.get(Number(route.request().url().match(/drawing-download-(\d+)/)[1])), contentType: 'application/pdf' }))
  await page.route(/\/reports\/v1\/native\/image-resize-fixture\/[123]$/, async route => route.fulfill({ response: await route.fetch({ url: `${base}/reports/v1/editor/assets/native.html` }) }))
  const open = async n => { await page.goto(`${base}/reports/v1/native/image-resize-fixture/${n}`); await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 3 && document.querySelector('.pdf-page canvas'), null, { timeout: 60000 }) }
  const ops = () => page.evaluate(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.includes('image-resize-fixture'))?.[1] ?? '{"operations":[]}').operations)
  const panel = page.locator('.pdf-pending-drawings-panel'), rows = panel.locator('[data-pdf-pending-drawing]')
  const show = async () => { await page.locator('[data-pdf-ribbon-tab="annotate"]').click(); await page.getByRole('button', { name: '待保存绘图', exact: true }).click() }
  const loaded = () => page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 3 && document.querySelector('.pdf-page canvas'), null, { timeout: 60000 })
  const preview = async () => { await page.locator('[data-pdf-ribbon-tab="edit"]').click(); await page.getByRole('button', { name: '校验当前修改', exact: true }).click(); await page.waitForFunction(() => document.querySelector('.native-pdf-editor')?.dataset.pdfPreview === 'true', null, { timeout: 30000 }); await loaded() }
  const save = async n => { await page.locator('[data-action="save"]').click(); await page.waitForFunction(n => document.querySelector('.save-state-label')?.textContent === `已保存修订 ${n}`, n, { timeout: 30000 }); const link = await page.locator('.native-delivery a').filter({ hasText: '下载 PDF' }).getAttribute('href'); const bytes = Buffer.from(await page.evaluate(async url => [...new Uint8Array(await (await fetch(url)).arrayBuffer())], link)); assert.deepEqual(bytes, revisions.get(n)) }
  await open(1)
  const content = page.locator('.pdf-page').first().locator('.pdf-page-content')
  const addImage = async () => {
    await page.locator('input[aria-label="选择要插入的图像"]').setInputFiles({ name: 'pattern.png', mimeType: 'image/png', buffer: Buffer.from(fixture.image,'base64') })
    await page.waitForFunction(() => document.querySelector('.native-pdf-editor')?.dataset.pdfMode==='draw')
    await content.scrollIntoViewIfNeeded(); const box = await content.boundingBox()
    await page.mouse.move(box.x+box.width*.2,box.y+box.height*.3);await page.mouse.down()
    await page.mouse.move(box.x+box.width*.4,box.y+box.height*.45,{steps:4});await page.mouse.up();await loaded()
  }
  await addImage();await page.waitForFunction(() => document.querySelectorAll('[data-pdf-drawing="image"]').length===1)
  await addImage();await page.waitForFunction(() => document.querySelectorAll('[data-pdf-drawing="image"]').length===2)
  const twins=await ops();assert.deepEqual(twins[0],twins[1]);assert.equal(twins[0].shape,'image')
  await page.locator('[data-pdf-ribbon-tab="page"]').click()
  await page.locator('[data-source-command-id="genoffice.pdf.page.rotateRight"]').click();await loaded()
  await page.locator('[data-source-command-id="genoffice.pdf.page.reverse"]').click();await loaded()
  await show();assert.equal(await rows.count(),2)
  const original=await ops()
  await rows.first().getByRole('button').evaluate(node=>{window.__oldImageSelection=node})
  await rows.last().getByRole('button',{name:'选择此绘图'}).click()
  await page.evaluate(()=>window.__oldImageSelection.click());assert.match(await panel.innerText(),/已选择草稿操作 #2/)
  const dialog=page.getByRole('dialog',{name:'缩放待保存图像',exact:true})
  const resize=panel.getByRole('button',{name:'缩放所选图像',exact:true})
  await resize.click();await dialog.locator('form').evaluate(node=>{window.__cancelledResize=node})
  await dialog.getByRole('button',{name:'取消',exact:true}).click()
  await page.evaluate(()=>window.__cancelledResize.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})))
  assert.deepEqual(await ops(),original)
  await resize.click();await dialog.locator('form').evaluate(node=>{window.__replacedResize=node})
  await resize.evaluate(node=>node.click())
  await page.evaluate(()=>window.__replacedResize.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})))
  assert.deepEqual(await ops(),original);assert.equal(await page.locator('.pdf-pending-drawing-dialog[open]').count(),1)
  await dialog.getByLabel('缩放百分比',{exact:true}).fill('9999')
  await dialog.getByRole('button',{name:'应用缩放',exact:true}).click()
  assert.match(await dialog.getByRole('alert').innerText(),/页面内/);assert.deepEqual(await ops(),original)
  await dialog.getByLabel('缩放百分比',{exact:true}).fill('-50')
  await dialog.getByRole('button',{name:'应用缩放',exact:true}).click()
  assert.match(await dialog.getByRole('alert').innerText(),/正的有限/);assert.deepEqual(await ops(),original)
  await page.locator('[data-pdf-ribbon-tab="home"]').evaluate(node=>node.click())
  await page.getByRole('button',{name:/^(撤销|Undo)$/}).evaluate(node=>node.click());await loaded()
  const stale=await ops();await dialog.getByLabel('缩放百分比',{exact:true}).fill('50')
  await dialog.getByRole('button',{name:'应用缩放',exact:true}).click()
  assert.match(await dialog.getByRole('alert').innerText(),/已变化/);assert.deepEqual(await ops(),stale)
  await dialog.getByRole('button',{name:'取消',exact:true}).click()
  await page.getByRole('button',{name:/^(重做|Redo)$/}).click();await loaded();assert.deepEqual(await ops(),original)
  await rows.last().getByRole('button',{name:'选择此绘图'}).click();await resize.click()
  await dialog.getByLabel('缩放百分比',{exact:true}).fill('50')
  await dialog.getByLabel('固定角（原始 PDF 坐标）',{exact:true}).selectOption('top-right')
  await dialog.getByRole('button',{name:'应用缩放',exact:true}).click();await loaded()
  const resized=await ops(),[x1,y1,x2,y2]=original[1].rect,expectedRect=[(x1+x2)/2,(y1+y2)/2,x2,y2]
  assert.deepEqual(resized[0],original[0]);assert.deepEqual(resized[1],{...original[1],rect:expectedRect});assert.deepEqual(resized.slice(2),original.slice(2))
  await page.getByRole('button',{name:/^(撤销|Undo)$/}).click();await loaded();assert.deepEqual(await ops(),original)
  await page.getByRole('button',{name:/^(重做|Redo)$/}).click();await loaded();assert.deepEqual(await ops(),resized)
  await page.reload();await loaded();await page.locator('.pdf-page-label').last().click();await show();assert.deepEqual(await ops(),resized)
  await rows.last().getByRole('button',{name:'选择此绘图'}).click();assert.equal(await resize.isEnabled(),true)
  await preview();assert.equal(await resize.isDisabled(),true)
  await save(2)
  if(process.env.PDF_IMAGE_RESIZE_EVIDENCE_DIR){const dir=process.env.PDF_IMAGE_RESIZE_EVIDENCE_DIR;await mkdir(dir,{recursive:true});await writeFile(`${dir}/actual-download.pdf`,revisions.get(2));await writeFile(`${dir}/source.pdf`,source);await writeFile(`${dir}/saved-operations.json`,JSON.stringify(payloads[0].operations,null,2))}
  const independent=python({mode:'verify',source:fixture.bytes,bytes:revisions.get(2).toString('base64'),rects:[original[0].rect,expectedRect],imagePixelsSha256:fixture.imagePixelsSha256})
  await open(2);await show();assert.equal(await rows.count(),0)
  readonly=true;await open(1);await page.locator('[data-pdf-ribbon-tab="annotate"]').click()
  await addImage();assert.deepEqual(await ops(),[])
  assert.deepEqual(errors,[])
  const evidence={ok:true,independent,browserVersion:browser.version(),revisions:[...revisions].map(([revision,bytes])=>({revision,sha256:sha(bytes),size:bytes.length})),operations:payloads.map(input=>input.operations),exactTwinResize:true,aspectAndFixedCorner:true,cancelReplacedAndStaleModalRefused:true,undoRedoReload:true,rotatedReordered:true,previewActualDownloadReopen:true,readonlyIsolation:true,provenance:'production static Web percentage/anchor modal; substituted auth/revision routes; actual packed engine/PDF.js/download and independent pypdf AP/image pixels; no desktop corner-drag equivalence or production acceptance'}
  if (process.env.PDF_IMAGE_RESIZE_EVIDENCE_DIR) { const dir = process.env.PDF_IMAGE_RESIZE_EVIDENCE_DIR; await mkdir(dir, { recursive: true }); for (const [n, bytes] of revisions) await writeFile(`${dir}/revision-${n}.pdf`, bytes); await writeFile(`${dir}/evidence.json`, JSON.stringify(evidence, null, 2)); await page.screenshot({ path: `${dir}/readonly-reopen.png`, fullPage: true }) }
  console.log(JSON.stringify(evidence))
} finally { await browser?.close(); server.kill('SIGTERM') }
