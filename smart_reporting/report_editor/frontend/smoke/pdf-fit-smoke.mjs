import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { mkdir, writeFile, readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.PDF_FIT_SMOKE_PORT ?? 4210), base = `http://127.0.0.1:${port}`, sha = bytes => createHash('sha256').update(bytes).digest('hex')
function python(input) {
  const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import json,sys,base64
from io import BytesIO
from pypdf import PdfReader,PdfWriter
from pypdf.generic import NameObject,DictionaryObject,ArrayObject,NumberObject,TextStringObject
from smart_reporting.reporting.tests.test_pdf_page_size import size_fixture
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf,patch_pdf,patch_pdf_with_receipt
p=json.load(sys.stdin)
if p['mode']=='create':
 from pypdf.generic import DecodedStreamObject,RectangleObject
 w=PdfWriter(clone_from=PdfReader(BytesIO(size_fixture())));sizes=[(900,600),(100,600),(100,500),(900,500),(600,1400)]
 for index,(width,height) in enumerate(sizes):
  page=w.pages[index] if index<3 else w.add_blank_page(width,height)
  page[NameObject('/MediaBox')]=RectangleObject([0,0,width,height]);page[NameObject('/CropBox')]=RectangleObject([0,0,width,height]);page[NameObject('/Rotate')]=NumberObject(0);page.pop(NameObject('/UserUnit'),None)
  if index>=3:
   stream=DecodedStreamObject();stream.set_data(b'0.2 0.4 0.6 rg 20 20 40 40 re f');page[NameObject('/Contents')]=w._add_object(stream)
 out=BytesIO();w.write(out);b=out.getvalue();print(json.dumps({'bytes':base64.b64encode(b).decode(),'model':inspect_pdf(b)}))
elif p['mode']=='inspect':print(json.dumps(inspect_pdf(base64.b64decode(p['bytes']))))
elif p['mode']=='patch':
 b=base64.b64decode(p['bytes']);r=patch_pdf_with_receipt(b,p['operations']);r['bytes']=base64.b64encode(r.pop('content')).decode();r['model']=inspect_pdf(base64.b64decode(r['bytes']));print(json.dumps(r))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw Error(result.stderr)
  return JSON.parse(result.stdout)
}
const fixture = python({ mode: 'create' }), source = Buffer.from(fixture.bytes, 'base64'), revisions = new Map([[1, source], [2, source]])
let browser, readonly = false, savedOperations, previewBytes
const server = spawn('./node_modules/.bin/vite', ['preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
try {
  for (let n = 0; n < 100; n++) { try { if ((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true, executablePath: '/usr/bin/chromium' })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true }), errors = []
  page.on('pageerror', error => errors.push(error.message)); page.on('console', entry => { if (entry.type() === 'error') errors.push(entry.text()) })
  const revision = route => Number(route.request().url().match(/fit-fixture\/(\d+)\/api/)[1]), active = route => revisions.get(revision(route))
  const inspect = bytes => python({ mode: 'inspect', bytes: bytes.toString('base64') }), patch = (bytes, operations) => python({ mode: 'patch', bytes: bytes.toString('base64'), operations })
  await page.route('**/reports/v1/native/fit-fixture/*/api/context', route => route.fulfill({ json: {
    context: { documentId: 'fit-fixture', revision: revision(route), parentRevision: null, format: 'pdf', origin: 'upload', scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' }, sourceFile: { path: 'attachments.pdf', size: active(route).length, sha256: sha(active(route)), mediaType: 'application/pdf' } }, csrfToken: 'fixture', capabilities: { pdf_editor: true }, editingEnabled: !readonly,
  } }))
  await page.route('**/reports/v1/native/fit-fixture/*/api/file', route => route.fulfill({ body: active(route), contentType: 'application/pdf' }))
  await page.route('**/reports/v1/native/fit-fixture/*/api/preview', route => {
    const bytes = active(route), ops = route.request().postDataJSON().operations, result = ops.length ? patch(bytes,ops) : null
    return route.fulfill({ json: { sourceSha256: sha(bytes), model: result?.model ?? inspect(bytes), appliedOperationIndices: result?.appliedOperationIndices ?? [], skippedOperations: [], previewDigest: result?.previewDigest } })
  })
  await page.route('**/reports/v1/native/fit-fixture/*/api/preview.pdf', route => {
    const input = route.request().postDataJSON(), result = patch(active(route),input.operations); previewBytes=Buffer.from(result.bytes,'base64'); assert.equal(input.expectedPreviewDigest,result.previewDigest)
    return route.fulfill({ body: Buffer.from(result.bytes,'base64'), contentType:'application/pdf', headers: { 'X-Native-Preview-Digest':result.previewDigest } })
  })
  await page.route(/\/reports\/v1\/native\/fit-fixture\/[123]$/, async route => route.fulfill({ response: await route.fetch({ url:`${base}/reports/v1/editor/assets/native.html` }) }))
  const open = async n => {await page.goto(`${base}/reports/v1/native/fit-fixture/${n}`);await page.waitForFunction(()=>document.querySelectorAll('.pdf-page').length===5&&document.querySelector('.pdf-page canvas'),null,{timeout:60000})}
  const zoom=page.getByLabel('页面缩放',{exact:true}), width=page.locator('[data-source-command-id="genoffice.pdf.view.pageZoom.fitWidth"]'), whole=page.locator('[data-source-command-id="genoffice.pdf.view.pageZoom.fitPage"]'), spread=page.locator('[data-source-command-id="genoffice.pdf.view.navigation.pageSpread"]')
  const ops=()=>page.evaluate(()=>JSON.parse(Object.entries(localStorage).find(([key])=>key.includes('native-editor-draft')&&key.includes('fit-fixture'))?.[1]??'{"operations":[]}').operations)
  const settle=async(mode,count=5)=>{
    const handle=await page.waitForFunction(({mode,count})=>{
      const v=document.querySelector('.pdf-document-pages');if(!v)return false
      const rows=[...v.querySelectorAll('.pdf-page-row')],pages=[...v.querySelectorAll('.pdf-page')];if(pages.length!==count)return false
      const style=getComputedStyle(v),n=s=>parseFloat(s)||0,w=v.clientWidth-n(style.paddingLeft)-n(style.paddingRight),h=v.clientHeight-n(style.paddingTop)-n(style.paddingBottom)
      const rowWidths=rows.map(row=>row.getBoundingClientRect().width),canvasHeights=pages.map(p=>{const c=p.querySelector('.pdf-page-content'),s=getComputedStyle(p);return c.getBoundingClientRect().bottom-p.getBoundingClientRect().top+n(s.paddingBottom)+n(s.borderBottomWidth)})
      const maxW=Math.max(...rowWidths),maxH=Math.max(...canvasHeights),scale=Number(document.querySelector('[aria-label="页面缩放"]')?.value)
      const fits=maxW<=w+1&&(mode!=='page'||maxH<=h+1),tight=Math.abs(maxW-w)<1.5||(mode==='page'&&Math.abs(maxH-h)<1.5)
      const signature=JSON.stringify([scale,w,h,rowWidths,canvasHeights]),previous=window.__fitGeometry
      const stable=previous?.signature===signature?previous.stable+1:0;window.__fitGeometry={signature,stable}
      return fits&&tight&&stable>=3?{scale,availableWidth:w,availableHeight:h,rowWidths,canvasHeights,rows:rows.map(row=>row.children.length)}:false
    },{mode,count});return await handle.jsonValue()
  }
  const frames=()=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))
  await open(1);await page.locator('.pdf-page-label').nth(1).click();const selected=await page.locator('.pdf-page.is-active').getAttribute('data-page-id')
  await page.locator('[data-pdf-ribbon-tab="view"]').click();await width.click();const single=await settle('width');assert.equal(single.rows.length,5);assert.equal(await page.locator('.pdf-page.is-active').getAttribute('data-page-id'),selected)
  await spread.click();const pairs=await settle('width');assert.deepEqual(pairs.rows,[2,2,1]);assert.ok(pairs.scale<single.scale);assert.ok(Math.abs(pairs.rowWidths[0]-pairs.rowWidths[1])<1)
  await page.setViewportSize({width:1060,height:920});const resized=await settle('width');assert.notEqual(resized.scale,pairs.scale)
  await page.locator('[data-source-command-id="genoffice.pdf.view.navigation.thumbnails"]').click();const noSidebar=await settle('width');assert.ok(noSidebar.scale>resized.scale)
  await page.locator('[data-source-command-id="genoffice.pdf.view.navigation.comments"]').click();const commentsSidebar=await settle('width');assert.ok(commentsSidebar.scale<noSidebar.scale)
  await whole.click();const fittedPage=await settle('page');assert.ok(fittedPage.scale<commentsSidebar.scale)
  await page.setViewportSize({width:1060,height:1100});const taller=await settle('page');assert.ok(taller.scale>fittedPage.scale)
  await page.locator('[data-pdf-ribbon-tab="home"]').click();await zoom.selectOption('1');await page.waitForFunction(()=>document.querySelector('.pdf-page-content')?.style.width==='900px');await page.setViewportSize({width:800,height:900});await frames();assert.equal(Number(await zoom.inputValue()),1);assert.deepEqual(await ops(),[])
  await page.locator('[data-pdf-ribbon-tab="view"]').click();await width.click();await settle('width');await page.reload();await page.waitForFunction(()=>document.querySelectorAll('.pdf-page').length===5);const reopened=await settle('width');assert.deepEqual(reopened.rows,[1,1,1,1,1])
  await page.locator('[data-pdf-ribbon-tab="fillForm"]').click();const contact=page.getByLabel('contact',{exact:true});await contact.fill('uncommitted during fit')
  const beforeInputResize=Number(await zoom.inputValue());await page.setViewportSize({width:950,height:950});await settle('width');assert.notEqual(Number(await zoom.inputValue()),beforeInputResize);assert.equal(await contact.inputValue(),'uncommitted during fit');assert.ok(await contact.evaluate(control=>control===document.activeElement));assert.deepEqual(await ops(),[])
  await contact.press('Tab');await page.waitForFunction(()=>Object.entries(localStorage).some(([key,value])=>key.includes('native-editor-draft')&&JSON.parse(value).operations?.some(op=>op.kind==='setFormValue')))
  await page.locator('[data-pdf-ribbon-tab="home"]').click();await page.getByRole('button',{name:/^(撤销|Undo)$/}).click();await page.waitForFunction(()=>Object.entries(localStorage).some(([key,value])=>key.includes('native-editor-draft')&&JSON.parse(value).operations?.length===0))
  await page.locator('[data-pdf-ribbon-tab="view"]').click();await spread.click();await whole.click();await settle('page')
  await page.locator('[data-pdf-ribbon-tab="annotate"]').click();await page.locator('[data-source-command-id="genoffice.pdf.annotate.drawTools.note"]').click();await page.getByLabel('文字批注内容').fill('fit preview note');await settle('page');await page.locator('.pdf-page-content').first().scrollIntoViewIfNeeded();await page.waitForFunction(()=>document.querySelector('.pdf-page-content')?.onpointerup);await page.locator('.pdf-page-content').first().click({position:{x:100,y:80}});await page.waitForFunction(()=>document.querySelectorAll('.pdf-pending-note').length===1);await settle('page')
  await page.locator('.pdf-page-label').nth(1).click();await page.locator('[data-pdf-ribbon-tab="page"]').click();await page.locator('[data-source-command-id="genoffice.pdf.page.rotateRight"]').click();const rotated=await settle('page')
  await page.locator('.pdf-page-label').nth(4).click();await page.locator('[data-source-command-id="genoffice.pdf.page.delete"]').click();const deleted=await settle('page',4);assert.ok(deleted.scale>rotated.scale)
  const draftBeforePreview=await ops();assert.deepEqual(draftBeforePreview.map(op=>op.kind),['addTextAnnotation','rotatePage','deletePage','reorderPages']);assert.deepEqual(draftBeforePreview.at(-1).pageIds,fixture.model.pages.slice(0,4).map(page=>page.pageId))
  await page.locator('[data-pdf-ribbon-tab="view"]').click();await width.click();const beforePreview=await settle('width',4)
  await page.locator('[data-pdf-ribbon-tab="edit"]').click();await page.getByRole('button',{name:'校验当前修改',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.native-pdf-editor')?.dataset.pdfPreview==='true');const preview=await settle('width',4)
  await page.setViewportSize({width:1000,height:1000});const previewResized=await settle('width',4);assert.notEqual(previewResized.scale,preview.scale)
  await page.getByRole('button',{name:'返回原稿编辑',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.native-pdf-editor')?.dataset.pdfPreview==='false');const returned=await settle('width',4);assert.deepEqual(await ops(),draftBeforePreview)
  const downloaded=Buffer.from(await page.evaluate(async()=>[...new Uint8Array(await(await fetch('/reports/v1/native/fit-fixture/1/api/file')).arrayBuffer())]));assert.deepEqual(downloaded,source)
  assert.ok(await zoom.locator('option').count()<=19)
  readonly=true;await open(2);await page.locator('[data-pdf-ribbon-tab="view"]').click();await spread.click();await whole.click();const readonlyFit=await settle('page');await page.setViewportSize({width:650,height:1000});const mobile=await settle('page');assert.deepEqual(await ops(),draftBeforePreview);assert.ok(await page.evaluate(()=>Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft')).map(([,value])=>JSON.parse(value)).filter(d=>d.identity.revision===2).every(d=>d.operations.length===0)))
  // A queued resize must not revive the editor after the real pagehide teardown.
  await page.evaluate(()=>{window.dispatchEvent(new Event('resize'));window.dispatchEvent(new Event('pagehide'))});await frames();assert.equal(await page.locator('.pdf-page').count(),0);assert.deepEqual(errors,[])
  const evidence={ok:true,browserVersion:browser.version(),sourceSha256:sha(source),downloadedSha256:sha(downloaded),previewSha256:sha(previewBytes),single,pairs,resized,noSidebar,commentsSidebar,fittedPage,taller,reopened,rotated,deleted,beforePreview,preview,previewResized,returned,readonlyFit,mobile,selectionPreserved:true,uncommittedFormInputPreserved:true,manualZoomStopsFit:true,queuedDisposeSafe:true,operations:draftBeforePreview,provenance:'production static UI, actual PDF.js/packed engine; substituted authorization/revision routes; DOM bounds independently prove fit; no desktop/production claim'}
  const dir=process.env.PDF_FIT_EVIDENCE_DIR;if(dir){await mkdir(dir,{recursive:true});await writeFile(`${dir}/source.pdf`,source);await writeFile(`${dir}/preview.pdf`,previewBytes);await writeFile(`${dir}/downloaded.pdf`,downloaded);await writeFile(`${dir}/evidence.json`,JSON.stringify(evidence,null,2))}
  console.log(JSON.stringify(evidence))
} catch(error){const dir=process.env.PDF_FIT_EVIDENCE_DIR;if(dir&&browser){await mkdir(dir,{recursive:true});const page=browser.contexts()[0]?.pages()[0];if(page){await writeFile(`${dir}/failure.json`,JSON.stringify({error:String(error),state:await page.evaluate(()=>({text:document.body.innerText,fit:window.__fitGeometry,storage:{...localStorage}}))},null,2));await page.screenshot({path:`${dir}/failure.png`,fullPage:true})}};throw error
} finally {await browser?.close();server.kill('SIGTERM')}
