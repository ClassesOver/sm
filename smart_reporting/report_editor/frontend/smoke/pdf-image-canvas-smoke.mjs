import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.PDF_IMAGE_CANVAS_SMOKE_PORT ?? 4218), base = `http://127.0.0.1:${port}`, sha = bytes => createHash('sha256').update(bytes).digest('hex')
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
 b=size_fixture();image=Image.new('RGB',(8,8));image.putdata([(255,0,0) if x<4 and y<4 else (0,255,0) if x>=4 and y<4 else (0,0,255) if x<4 else (255,255,0) for y in range(8) for x in range(8)]);png=BytesIO();image.save(png,format='PNG');print(json.dumps({'bytes':base64.b64encode(b).decode(),'model':inspect_pdf(b),'image':base64.b64encode(png.getvalue()).decode(),'imagePixelsSha256':sha256(image.tobytes()).hexdigest()}))
elif p['mode']=='pixels':
 image=Image.open(BytesIO(base64.b64decode(p['bytes']))).convert('RGB');samples=[image.getpixel((round(image.width*x),round(image.height*y))) for x,y in [(0.25,0.25),(0.75,0.25),(0.25,0.75),(0.75,0.75)]]
 expected=[(255,0,0),(0,255,0),(0,0,255),(255,255,0)]
 assert all(max(abs(a-b) for a,b in zip(actual,want))<12 for actual,want in zip(samples,expected)),samples
 print(json.dumps({'quadrants':samples,'upright':True}))
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
  assert image['/Width']==8 and image['/Height']==8 and str(image['/ColorSpace'])=='/DeviceRGB'
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
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 2 }), errors = []
  page.on('pageerror', error => errors.push(error.message)); page.on('console', entry => { if (entry.type() === 'error') errors.push(entry.text()) })
  const revision = route => Number(route.request().url().match(/image-canvas-fixture\/(\d+)\/api/)[1]), active = route => revisions.get(revision(route))
  const inspect = bytes => python({ mode: 'inspect', bytes: bytes.toString('base64') }), patch = (bytes, operations) => python({ mode: 'patch', bytes: bytes.toString('base64'), operations })
  await page.route('**/reports/v1/native/image-canvas-fixture/*/api/context', route => route.fulfill({ json: {
    context: { documentId: 'image-canvas-fixture', revision: revision(route), parentRevision: revision(route) === 1 ? null : revision(route) - 1, format: 'pdf', origin: 'upload', scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' }, sourceFile: { path: 'drawings.pdf', size: active(route).length, sha256: sha(active(route)), mediaType: 'application/pdf' } }, csrfToken: 'fixture', capabilities: { pdf_editor: true }, editingEnabled: !readonly,
  } }))
  await page.route('**/reports/v1/native/image-canvas-fixture/*/api/file', route => route.fulfill({ body: active(route), contentType: 'application/pdf' }))
  await page.route('**/reports/v1/native/image-canvas-fixture/*/api/preview', route => {
    const bytes = active(route), ops = route.request().postDataJSON().operations, result = ops.length ? patch(bytes, ops) : null
    return route.fulfill({ json: { sourceSha256: sha(bytes), model: result?.model ?? inspect(bytes), appliedOperationIndices: result?.appliedOperationIndices ?? [], skippedOperations: [], previewDigest: result?.previewDigest } })
  })
  await page.route('**/reports/v1/native/image-canvas-fixture/*/api/preview.pdf', route => {
    const input = route.request().postDataJSON(), result = patch(active(route), input.operations); assert.equal(input.expectedPreviewDigest, result.previewDigest)
    return route.fulfill({ body: Buffer.from(result.bytes, 'base64'), contentType: 'application/pdf', headers: { 'X-Native-Preview-Digest': result.previewDigest } })
  })
  await page.route('**/reports/v1/native/image-canvas-fixture/*/api/save', route => {
    const input = route.request().postDataJSON(), result = patch(active(route), input.operations), next = revision(route) + 1, bytes = Buffer.from(result.bytes, 'base64'); payloads.push(input); revisions.set(next, bytes)
    return route.fulfill({ json: { documentId: 'image-canvas-fixture', revision: next, parentRevision: next - 1, revisionRegistered: true, artifacts: { pdf: { downloadUrl: `/drawing-download-${next}.pdf`, size: bytes.length, sha256: sha(bytes) } }, editor: { openUrl: `/reports/v1/native/image-canvas-fixture/${next}` }, validation: { ok: false, issues: [{ code: 'manual_review', message: '请核验内容；下载仍可用' }] } } })
  })
  await page.route(/\/drawing-download-\d+\.pdf$/, route => route.fulfill({ body: revisions.get(Number(route.request().url().match(/drawing-download-(\d+)/)[1])), contentType: 'application/pdf' }))
  await page.route(/\/reports\/v1\/native\/image-canvas-fixture\/[123]$/, async route => route.fulfill({ response: await route.fetch({ url: `${base}/reports/v1/editor/assets/native.html` }) }))
  const open = async n => { await page.goto(`${base}/reports/v1/native/image-canvas-fixture/${n}`); await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 3 && document.querySelector('.pdf-page canvas'), null, { timeout: 60000 }) }
  const ops = () => page.evaluate(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.includes('image-canvas-fixture'))?.[1] ?? '{"operations":[]}').operations)
  const panel = page.locator('.pdf-pending-drawings-panel'), rows = panel.locator('[data-pdf-pending-drawing]')
  const show = async () => { await page.locator('[data-pdf-ribbon-tab="annotate"]').click(); await page.getByRole('button', { name: '待保存绘图', exact: true }).click() }
  const loaded = () => page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 3 && document.querySelector('.pdf-page canvas'), null, { timeout: 60000 })
  const preview = async () => { await page.locator('[data-pdf-ribbon-tab="edit"]').click(); await page.getByRole('button', { name: '校验当前修改', exact: true }).click(); await page.waitForFunction(() => document.querySelector('.native-pdf-editor')?.dataset.pdfPreview === 'true', null, { timeout: 30000 }); await page.waitForFunction(()=>[...document.querySelectorAll('button')].some(node=>node.textContent?.trim()==='校验当前修改'&&!node.disabled)); await loaded() }
  const save = async n => { await page.locator('[data-action="save"]').click(); await page.waitForFunction(n => document.querySelector('.save-state-label')?.textContent === `已保存修订 ${n}`, n, { timeout: 30000 }); const link = await page.locator('.native-delivery a').filter({ hasText: '下载 PDF' }).getAttribute('href'); const bytes = Buffer.from(await page.evaluate(async url => [...new Uint8Array(await (await fetch(url)).arrayBuffer())], link)); assert.deepEqual(bytes, revisions.get(n)) }
  const evidenceDir = process.env.PDF_IMAGE_CANVAS_EVIDENCE_DIR
  if (evidenceDir) await mkdir(evidenceDir,{recursive:true})
  const phase = label => console.log(JSON.stringify({ phase: label }))
  const image = (index=1) => page.locator(`image[data-pdf-drawing="image"][data-pdf-image-index="${index}"]`)
  const content = () => page.locator('.pdf-page').last().locator('.pdf-page-content')
  const selectMode = async () => { await page.locator('[data-pdf-ribbon-tab="annotate"]').click();await page.getByRole('button',{name:'选择文字',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.native-pdf-editor')?.dataset.pdfMode==='select') }
  const history = async direction => { await page.locator('[data-pdf-ribbon-tab="home"]').click();await page.getByRole('button',{name:direction==='undo'?/^(撤销|Undo)$/:/^(重做|Redo)$/}).click();await loaded() }
  const point = async (index=1) => { const node=image(index);await node.scrollIntoViewIfNeeded();const box=await node.boundingBox();assert.ok(box&&box.width>4&&box.height>4);return {x:box.x+box.width/2,y:box.y+box.height/2,box} }
  const closeNumbers = (actual,expected,epsilon=1e-6) => { assert.equal(actual.length,expected.length);actual.forEach((value,index)=>assert.ok(Math.abs(value-expected[index])<epsilon,`${actual} != ${expected}`)) }
  const startDrag = async (dx=20,dy=12,index=1) => { const p=await point(index);await page.mouse.move(p.x,p.y);await page.mouse.down();await page.mouse.move(p.x+dx,p.y+dy,{steps:5});return p }
  const pixels = async (label,box) => {const bytes=await page.screenshot({clip:{x:box.x,y:box.y,width:box.width,height:box.height}});if(evidenceDir)await writeFile(`${evidenceDir}/${label}.png`,bytes);return python({mode:'pixels',bytes:bytes.toString('base64')})}
  phase('create-upload-twins')
  await open(1)
  const sourceContent=page.locator('.pdf-page').first().locator('.pdf-page-content')
  const addImage=async()=>{
    await page.locator('input[aria-label="选择要插入的图像"]').setInputFiles({name:'quadrants.png',mimeType:'image/png',buffer:Buffer.from(fixture.image,'base64')})
    await page.waitForFunction(()=>document.querySelector('.native-pdf-editor')?.dataset.pdfMode==='draw')
    await sourceContent.scrollIntoViewIfNeeded();const box=await sourceContent.boundingBox()
    await page.mouse.move(box.x+box.width*.2,box.y+box.height*.3);await page.mouse.down();await page.mouse.move(box.x+box.width*.4,box.y+box.height*.45,{steps:5});await page.mouse.up();await loaded()
  }
  await addImage();await page.waitForFunction(()=>document.querySelectorAll('[data-pdf-drawing="image"]').length===1)
  await addImage();await page.waitForFunction(()=>document.querySelectorAll('[data-pdf-drawing="image"]').length===2)
  const twins=await ops();assert.deepEqual(twins[0],twins[1]);await selectMode()
  const clicked=await point();await page.mouse.click(clicked.x,clicked.y)
  await page.waitForFunction(()=>document.querySelectorAll('[data-pdf-image-handle]').length===4)
  assert.deepEqual(await ops(),twins)
  const initialOrientation=await pixels('draft-upright-0',clicked.box)
  phase('drag-one-release-one-history')
  const beforeMove=await ops(),p=await startDrag(48,24)
  assert.deepEqual(await ops(),beforeMove)
  const live=await image().boundingBox();assert.ok(Math.abs(live.x-p.box.x)>10||Math.abs(live.y-p.box.y)>10,'live drawing box should move before commit')
  await page.mouse.up();await loaded()
  const moved=await ops(),r=beforeMove[1].rect
  assert.deepEqual(moved[0],beforeMove[0]);assert.deepEqual({...moved[1],rect:r},beforeMove[1]);closeNumbers(moved[1].rect,[r[0]+48*(r[2]-r[0])/p.box.width,r[1]-24*(r[3]-r[1])/p.box.height,r[2]+48*(r[2]-r[0])/p.box.width,r[3]-24*(r[3]-r[1])/p.box.height])
  await history('undo');assert.deepEqual(await ops(),beforeMove)
  await history('redo');assert.deepEqual(await ops(),moved)
  phase('click-threshold-and-cancellation')
  await selectMode();await startDrag(1,1);await page.mouse.up();assert.deepEqual(await ops(),moved)
  for(const cause of ['pointercancel','lostcapture','Escape','blur','page-switch']){
    await startDrag()
    if(cause==='pointercancel')await image().evaluate(node=>node.dispatchEvent(new PointerEvent('pointercancel',{pointerId:1,bubbles:true})))
    else if(cause==='lostcapture'){const released=await page.evaluate(()=>{const owner=[...document.querySelectorAll('*')].find(node=>node.hasPointerCapture?.(1));if(!owner)return false;owner.releasePointerCapture(1);return true});assert.equal(released,true)}
    else if(cause==='Escape')await page.keyboard.press('Escape')
    else if(cause==='blur')await page.evaluate(()=>window.dispatchEvent(new Event('blur')))
    else await page.locator('.pdf-page-label').nth(1).evaluate(node=>node.click())
    await page.mouse.up();assert.deepEqual(await ops(),moved,cause)
    if(cause==='page-switch')await page.locator('.pdf-page-label').first().evaluate(node=>node.click())
  }
  // The old DOM may still receive a dispatched release after a zoom or an undo.
  await startDrag();await image().evaluate(node=>{window.__oldImageDrag=node})
  await page.getByRole('button',{name:'放大页面',exact:true}).evaluate(node=>node.click());await loaded();await page.mouse.up()
  await page.evaluate(()=>window.__oldImageDrag.dispatchEvent(new PointerEvent('pointerup',{pointerId:1,bubbles:true})));assert.deepEqual(await ops(),moved)
  await startDrag();await image().evaluate(node=>{window.__oldImageDrag=node})
  await page.locator('[data-pdf-ribbon-tab="home"]').evaluate(node=>node.click());await page.getByRole('button',{name:/^(撤销|Undo)$/}).evaluate(node=>node.click());await loaded();await page.mouse.up()
  await page.evaluate(()=>window.__oldImageDrag.dispatchEvent(new PointerEvent('pointerup',{pointerId:1,bubbles:true})));assert.deepEqual(await ops(),beforeMove)
  await history('redo');assert.deepEqual(await ops(),moved)
  phase('drawing-mode-pass-through')
  const modeSelection=await point();await page.mouse.click(modeSelection.x,modeSelection.y);await page.waitForFunction(()=>document.querySelectorAll('[data-pdf-image-handle]').length===4)
  await page.locator('[data-pdf-ribbon-tab="annotate"]').click();await page.locator('[data-pdf-draw-shape="rect"]').click()
  const drawAt=await point();await page.mouse.move(drawAt.x,drawAt.y);await page.mouse.down();await page.mouse.move(drawAt.x+22,drawAt.y+22,{steps:4});await page.mouse.up();await loaded()
  const withRect=await ops();assert.equal(withRect.at(-1).shape,'rect');assert.deepEqual(withRect.slice(0,2),moved)
  await history('undo');assert.deepEqual(await ops(),moved);await selectMode()
  phase('rotate-reorder-corner-resize')
  await page.locator('[data-pdf-ribbon-tab="page"]').click();await page.locator('[data-source-command-id="genoffice.pdf.page.rotateRight"]').click();await loaded()
  await page.locator('[data-source-command-id="genoffice.pdf.page.reverse"]').click();await loaded();await page.locator('.pdf-page-label').last().click();await selectMode()
  const beforeResize=await ops(),body=await point();await page.mouse.click(body.x,body.y)
  await page.waitForFunction(()=>document.querySelectorAll('[data-pdf-image-handle]').length===4)
  const rotatedOrientation=await pixels('draft-upright-90',body.box)
  const handle=page.locator('[data-pdf-image-handle="0"]');const hb=await handle.boundingBox();assert.ok(hb)
  const corner={x:hb.x+hb.width/2,y:hb.y+hb.height/2}
  const finish={x:body.box.x+body.box.width/2,y:body.box.y+body.box.height/2}
  await page.mouse.move(corner.x,corner.y);await page.mouse.down();await page.mouse.move(finish.x,finish.y,{steps:6})
  assert.deepEqual(await ops(),beforeResize)
  await page.mouse.up();await loaded()
  const resized=await ops(),[x1,y1,x2,y2]=beforeResize[1].rect,expectedRect=[(x1+x2)/2,(y1+y2)/2,x2,y2]
  assert.deepEqual(resized[0],beforeResize[0]);closeNumbers(resized[1].rect,expectedRect,.5);assert.deepEqual(resized.slice(2),beforeResize.slice(2))
  const oldRatio=(x2-x1)/(y2-y1),rr=resized[1].rect;assert.ok(Math.abs((rr[2]-rr[0])/(rr[3]-rr[1])-oldRatio)<1e-8)
  await history('undo');assert.deepEqual(await ops(),beforeResize);await history('redo');assert.deepEqual(await ops(),resized)
  await page.reload();await loaded();await page.locator('.pdf-page-label').last().click();await selectMode();assert.deepEqual(await ops(),resized)
  // Save the source-page-relative box so the independent PDF.js output is sampled at the same region.
  const selectedBox=(await point()).box,holderBox=await content().boundingBox(),normalized={x:(selectedBox.x-holderBox.x)/holderBox.width,y:(selectedBox.y-holderBox.y)/holderBox.height,width:selectedBox.width/holderBox.width,height:selectedBox.height/holderBox.height}
  const finalDraftOrientation=await pixels('draft-final',selectedBox)
  const stored=await page.evaluate(()=>Object.entries(localStorage).find(([key])=>key.includes('image-canvas-fixture')))
  const rasterBox=async()=>{for(let attempt=0;attempt<3;attempt++){try{await content().scrollIntoViewIfNeeded();await content().locator('canvas').waitFor({state:'visible'});await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));const box=await content().boundingBox();if(!box)continue;return {x:box.x+normalized.x*box.width,y:box.y+normalized.y*box.height,width:normalized.width*box.width,height:normalized.height*box.height}}catch(error){if(!String(error).includes('not attached'))throw error}}throw Error('preview source-page canvas did not settle')}
  phase('actual-preview-save-reopen')
  await preview();assert.equal(await page.locator('[data-pdf-image-handle]').count(),0)
  const actualPreviewOrientation=await pixels('actual-preview',await rasterBox())
  await save(2)
  if(evidenceDir){await writeFile(`${evidenceDir}/actual-download.pdf`,revisions.get(2));await writeFile(`${evidenceDir}/source.pdf`,source);await writeFile(`${evidenceDir}/saved-operations.json`,JSON.stringify(payloads[0].operations,null,2))}
  const independent=python({mode:'verify',source:fixture.bytes,bytes:revisions.get(2).toString('base64'),rects:[resized[0].rect,resized[1].rect],imagePixelsSha256:fixture.imagePixelsSha256})
  await open(2);await page.locator('.pdf-page-label').last().click();assert.equal(await page.locator('[data-pdf-image-index]').count(),0)
  const savedOrientation=await pixels('saved-reopen',await rasterBox())
  phase('readonly-existing-draft-isolation')
  readonly=true;await page.evaluate(([key,value])=>localStorage.setItem(key,value),stored);await open(1);await page.locator('.pdf-page-label').last().click();await selectMode()
  const readonlyOps=await ops();assert.deepEqual(readonlyOps,resized)
  const ro=await point();await page.mouse.click(ro.x,ro.y);assert.equal(await page.locator('[data-pdf-image-handle]').count(),0)
  await startDrag();await page.mouse.up();assert.deepEqual(await ops(),readonlyOps)
  await image().evaluate(node=>{node.style.pointerEvents='all';node.closest('svg').classList.add('is-interactive')})
  await startDrag();await page.mouse.up();assert.deepEqual(await ops(),readonlyOps)
  assert.deepEqual(errors,[])
  const evidence={ok:true,independent,browserVersion:browser.version(),dpr:2,initialOrientation,rotatedOrientation,finalDraftOrientation,actualPreviewOrientation,savedOrientation,exactTwinCanvasSelectionDragResize:true,releaseOnceHistory:true,cancellationAndStaleDomRefused:true,clickThresholdNoHistory:true,drawingModePassThrough:true,undoRedoReload:true,sourceRotationAndReorder:true,readonlyAndPreviewIsolation:true,operations:payloads.map(input=>input.operations),provenance:'production static canvas interaction; substituted auth/revision routes; actual packed engine/PDF.js/download, independent pypdf AP pixels and screenshot orientation; no full desktop/production/image acceptance'}
  if(evidenceDir){for(const [n,bytes] of revisions)await writeFile(`${evidenceDir}/revision-${n}.pdf`,bytes);await writeFile(`${evidenceDir}/evidence.json`,JSON.stringify(evidence,null,2))}
  console.log(JSON.stringify(evidence))
} finally { await browser?.close(); server.kill('SIGTERM') }
