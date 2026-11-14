import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { mkdir, writeFile, readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { observePdfBuiltAssets } from './pdf-object-dialog-checks.mjs'
const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.PDF_READING_SMOKE_PORT ?? 4209), base = `http://127.0.0.1:${port}`, sha = bytes => createHash('sha256').update(bytes).digest('hex')
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
 b=size_fixture();print(json.dumps({'bytes':base64.b64encode(b).decode(),'model':inspect_pdf(b)}))
elif p['mode']=='inspect':print(json.dumps(inspect_pdf(base64.b64decode(p['bytes']))))
elif p['mode']=='patch':
 b=base64.b64decode(p['bytes']);r=patch_pdf_with_receipt(b,p['operations']);r['bytes']=base64.b64encode(r.pop('content')).decode();r['model']=inspect_pdf(base64.b64decode(r['bytes']));print(json.dumps(r))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw Error(result.stderr)
  return JSON.parse(result.stdout)
}
const fixture = python({ mode: 'create' }), source = Buffer.from(fixture.bytes, 'base64'), revisions = new Map([[1, source], [2, source], [3, source]])
let browser, readonly = false, scopeUser = 'fixture', savedOperations, previewBytes
const server = spawn('./node_modules/.bin/vite', ['preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
try {
  for (let n = 0; n < 100; n++) { try { if ((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{}) })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true }), errors = []
  const builtAssets=await observePdfBuiltAssets(page)
  page.on('pageerror', error => errors.push(error.message)); page.on('console', entry => { if (entry.type() === 'error') errors.push(entry.text()) })
  await page.addInitScript(() => {
    const get = Storage.prototype.getItem, set = Storage.prototype.setItem
    const trace=(event,value)=>{
      const v=document.querySelector('.pdf-document-pages'),data=JSON.parse(get.call(sessionStorage,'reading-trace')??'[]')
      data.push({event,value,at:Date.now(),scrollTop:v?.scrollTop,busy:document.querySelector('#report-editor')?.getAttribute('aria-busy'),status:document.querySelector('.save-state-label')?.textContent})
      set.call(sessionStorage,'reading-trace',JSON.stringify(data.slice(-100)))
    }
    for(const event of ['beforeunload','pagehide'])window.addEventListener(event,()=>trace(event,get.call(localStorage,'genoffice-pdf-view-state')),true)
    Storage.prototype.getItem = function(key) { if (key === 'genoffice-pdf-view-state' && sessionStorage.getItem('block-reading') === 'yes') throw Error('fixture storage denied'); return get.call(this,key) }
    Storage.prototype.setItem = function(key,value) { if (key === 'genoffice-pdf-view-state' && sessionStorage.getItem('block-reading') === 'yes') throw Error('fixture quota exceeded'); if(key==='genoffice-pdf-view-state')trace('write',value); return set.call(this,key,value) }
    const raf = window.requestAnimationFrame
    window.requestAnimationFrame = function(callback) { return sessionStorage.getItem('delay-reading') === 'yes' ? setTimeout(() => raf.call(this,callback),350) : raf.call(this,callback) }
  })
  const revision = route => Number(route.request().url().match(/reading-fixture\/(\d+)\/api/)[1]), active = route => revisions.get(revision(route))
  const inspect = bytes => python({ mode: 'inspect', bytes: bytes.toString('base64') }), patch = (bytes, operations) => python({ mode: 'patch', bytes: bytes.toString('base64'), operations })
  await page.route('**/reports/v1/native/reading-fixture/*/api/context', route => route.fulfill({ json: {
    context: { documentId: 'reading-fixture', revision: revision(route), parentRevision: null, format: 'pdf', origin: 'upload', scope: { database: 'fixture', companyId: 'fixture', userId: scopeUser, threadId: 'fixture' }, sourceFile: { path: 'attachments.pdf', size: active(route).length, sha256: sha(active(route)), mediaType: 'application/pdf' } }, csrfToken: 'fixture', capabilities: { pdf_editor: true }, editingEnabled: !readonly,
  } }))
  await page.route('**/reports/v1/native/reading-fixture/*/api/file', route => route.fulfill({ body: active(route), contentType: 'application/pdf' }))
  await page.route('**/reports/v1/native/reading-fixture/*/api/preview', route => {
    const bytes = active(route), ops = route.request().postDataJSON().operations, result = ops.length ? patch(bytes,ops) : null
    return route.fulfill({ json: { sourceSha256: sha(bytes), model: result?.model ?? inspect(bytes), appliedOperationIndices: result?.appliedOperationIndices ?? [], skippedOperations: [], previewDigest: result?.previewDigest } })
  })
  await page.route('**/reports/v1/native/reading-fixture/*/api/preview.pdf', route => {
    const input = route.request().postDataJSON(), result = patch(active(route),input.operations); previewBytes = Buffer.from(result.bytes,'base64'); assert.equal(input.expectedPreviewDigest,result.previewDigest)
    return route.fulfill({ body: Buffer.from(result.bytes,'base64'), contentType:'application/pdf', headers: { 'X-Native-Preview-Digest':result.previewDigest } })
  })
  await page.route('**/reports/v1/native/reading-fixture/*/api/save', route => {
    const input = route.request().postDataJSON(), result = patch(active(route),input.operations); savedOperations = input.operations; const bytes = Buffer.from(result.bytes,'base64'); revisions.set(2,bytes)
    return route.fulfill({ json: { documentId:'reading-fixture',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{pdf:{downloadUrl:'/attachment-result.pdf',size:bytes.length,sha256:sha(bytes)}},editor:{openUrl:'/reports/v1/native/reading-fixture/2'},validation:{ok:false,issues:[{code:'manual_review',message:'下载仍可用'}]} } })
  })
  await page.route('**/attachment-result.pdf', route => route.fulfill({ body:revisions.get(2),contentType:'application/pdf' }))
  await page.route(/\/reports\/v1\/native\/reading-fixture\/[123]$/, async route => route.fulfill({ response: await route.fetch({ url:`${base}/reports/v1/editor/assets/native.html` }) }))
  const open = async n => { await page.goto(`${base}/reports/v1/native/reading-fixture/${n}`); await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 3 && document.querySelector('.pdf-page canvas') && document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000}) }
  const key = (revision=1,user=scopeUser) => `native-pdf:v1:native-editor-draft:v1:${JSON.stringify(['fixture','fixture',user,'fixture','reading-fixture',revision,sha(source)])}`
  const entry = (revision=1,user=scopeUser) => page.evaluate(key=>JSON.parse(localStorage.getItem('genoffice-pdf-view-state')??'{}')[key],key(revision,user))
  const flush = () => delay(360)
  const position = () => page.evaluate(()=>{
    const v=document.querySelector('.pdf-document-pages'), bounds=v.getBoundingClientRect(), rows=[...v.querySelectorAll('.pdf-page')].map(p=>({id:p.dataset.pageId,top:p.getBoundingClientRect().top-bounds.top-v.clientTop+v.scrollTop,height:p.getBoundingClientRect().height}))
    const r=rows.findLast(r=>r.top<=v.scrollTop)??rows[0];return {page:Number(r.id.split(':').at(-1))+1,frac:Math.max(0,Math.min(1,(v.scrollTop-r.top)/r.height)),scrollTop:v.scrollTop}
  })
  const scroll = (index,frac) => page.evaluate(({index,frac})=>{const v=document.querySelector('.pdf-document-pages'),p=[...v.querySelectorAll('.pdf-page')].find(p=>p.dataset.pageId.endsWith(`:page:${index}`));v.dispatchEvent(new Event('wheel',{bubbles:true}));v.scrollTop+=p.getBoundingClientRect().top-v.getBoundingClientRect().top-v.clientTop+p.getBoundingClientRect().height*frac;v.dispatchEvent(new Event('scroll'))},{index,frac})
  const waitSaved = async ({page:expectedPage,scale,fitMode},revision=1,user=scopeUser) => page.waitForFunction(({key,expectedPage,scale,fitMode})=>{const e=JSON.parse(localStorage.getItem('genoffice-pdf-view-state')??'{}')[key];return e&&e.page===expectedPage&&Math.abs(e.scale-scale)<1e-6&&e.fitMode===fitMode},{key:key(revision,user),expectedPage,scale,fitMode})
  const waitPosition = async saved => page.waitForFunction(saved=>{const v=document.querySelector('.pdf-document-pages');if(!v)return false;const top=v.getBoundingClientRect().top+v.clientTop,rows=[...v.querySelectorAll('.pdf-page')],p=rows.findLast(p=>p.getBoundingClientRect().top<=top)??rows[0];return p?.dataset.pageId.endsWith(`:page:${saved.page-1}`)&&Math.abs((top-p.getBoundingClientRect().top)/p.getBoundingClientRect().height-saved.frac)<.015},saved)
  const ops = () => page.evaluate(()=>JSON.parse(Object.entries(localStorage).find(([key])=>key.includes('native-editor-draft')&&key.includes('reading-fixture'))?.[1]??'{"operations":[]}').operations)
  await open(1)
  const zoom=page.getByLabel('页面缩放',{exact:true});await zoom.selectOption('1.5');await page.waitForFunction(()=>document.querySelector('.pdf-page-content')?.style.width==='570px')
  await scroll(1,.37);await waitSaved({page:2,scale:1.5,fitMode:null});const saved=await entry();assert.ok(Math.abs(saved.frac-.37)<.005);await waitPosition(saved)
  await page.evaluate(()=>sessionStorage.setItem('delay-reading','yes'));await page.reload();await page.waitForFunction(()=>document.querySelectorAll('.pdf-page').length===3)
  await page.evaluate(()=>{document.querySelector('.pdf-document-pages').dispatchEvent(new Event('scroll'))});await delay(320);assert.equal((await entry()).page,2);assert.ok(Math.abs((await entry()).frac-saved.frac)<.005)
  await waitPosition(saved);assert.equal(Number(await zoom.inputValue()),1.5);await page.evaluate(()=>sessionStorage.removeItem('delay-reading'))
  await page.setViewportSize({width:1100,height:850});await page.reload();await waitPosition(saved);assert.equal(Number(await zoom.inputValue()),1.5)
  await page.locator('[data-source-command-id="genoffice.pdf.home.pageZoom.fitWidth"]').click();await page.waitForFunction(()=>JSON.parse(localStorage.getItem('genoffice-pdf-view-state')??'{}')&&Object.values(JSON.parse(localStorage.getItem('genoffice-pdf-view-state')??'{}')).some(v=>v.fitMode==='width'))
  const fitted=await entry();await page.setViewportSize({width:900,height:850});await page.reload();await page.waitForFunction(()=>document.querySelectorAll('.pdf-page').length===3&&document.querySelector('.pdf-page canvas'));await page.waitForFunction(()=>Number(document.querySelector('[aria-label="页面缩放"]')?.value)!==1.5)
  const reopenedFit=Number(await zoom.inputValue());assert.ok(Math.abs(reopenedFit-fitted.scale)>.01);await waitSaved({page:2,scale:reopenedFit,fitMode:'width'})
  await zoom.selectOption('1.5');await page.waitForFunction(()=>document.querySelector('.pdf-page-content')?.style.width==='570px');await scroll(0,.2);await waitSaved({page:1,scale:1.5,fitMode:null})
  await page.locator('[data-pdf-ribbon-tab="page"]').click();await page.locator('[data-source-command-id="genoffice.pdf.page.reverse"]').click();await page.waitForFunction(()=>document.querySelector('.pdf-page')?.dataset.pageId.endsWith(':page:2'))
  await waitPosition({page:1,frac:.2});await flush();const afterReverse=await entry();await page.reload();await waitPosition(afterReverse);assert.equal(Number(await zoom.inputValue()),1.5)
  const beforeView=await ops();assert.equal(beforeView.length,1)
  // Make a real pending note so actual output preview executes the packed writer.
  await page.locator('[data-pdf-ribbon-tab="annotate"]').click();await page.locator('[data-source-command-id="genoffice.pdf.annotate.drawTools.note"]').click();await page.getByLabel('文字批注内容').fill('reading-state preview note');await page.locator('.pdf-page-content').first().scrollIntoViewIfNeeded();await page.waitForFunction(()=>document.querySelector('.pdf-page-content')?.onpointerup);await page.locator('.pdf-page-content').first().click({position:{x:120,y:90}});await page.waitForFunction(()=>document.querySelectorAll('.pdf-pending-note').length===1)
  await scroll(1,.3);await waitSaved({page:2,scale:1.5,fitMode:null});const beforePreview=await entry(),draftBeforePreview=await ops()
  await page.locator('[data-pdf-ribbon-tab="edit"]').click();await page.getByRole('button',{name:'校验当前修改',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.native-pdf-editor')?.dataset.pdfPreview==='true'&&document.querySelectorAll('.pdf-page').length===3)
  await page.waitForFunction(()=>[...document.querySelectorAll('button')].some(button=>button.textContent.trim()==='返回原稿编辑'&&!button.disabled))
  const frozenPreviewEntry=await entry();const {at:beforeAt,...beforeViewState}=beforePreview;const {at:previewAt,...previewViewState}=frozenPreviewEntry;assert.deepEqual(previewViewState,beforeViewState)
  await scroll(2,.1);await flush();assert.deepEqual(await entry(),frozenPreviewEntry)
  await page.getByRole('button',{name:'返回原稿编辑',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.native-pdf-editor')?.dataset.pdfPreview==='false');await waitPosition(beforePreview);assert.deepEqual(await ops(),draftBeforePreview)
  // Pagehide flushes the most recent position even before the 300ms debounce.
  await scroll(1,.42);await page.evaluate(()=>window.dispatchEvent(new Event('pagehide')));const flushed=await entry();assert.equal(flushed.page,2);assert.ok(Math.abs(flushed.frac-.42)<.005)
  readonly=true;await page.reload();await waitPosition(flushed);assert.equal(Number(await zoom.inputValue()),1.5)
  scopeUser='other-user';await open(1);await page.waitForFunction(()=>Number(document.querySelector('[aria-label="页面缩放"]')?.value)===1);await flush();assert.equal((await entry()).page,1)
  assert.equal((await entry(1,'fixture')).page,2)
  await open(2);await flush();assert.equal((await entry(2)).page,1);assert.equal(Number(await zoom.inputValue()),1)
  await scroll(1,.25);await waitSaved({page:2,scale:1,fitMode:null},2)
  await page.evaluate(()=>sessionStorage.setItem('delay-reading','yes'));await page.reload();await page.waitForFunction(()=>document.querySelectorAll('.pdf-page').length===3)
  const jump=page.locator('[data-source-command-id="genoffice.pdf.home.pageZoom.goToPage"]');await jump.fill('1');await jump.press('Enter');await waitSaved({page:1,scale:1,fitMode:null},2);assert.equal((await entry(2)).frac,0);await page.evaluate(()=>sessionStorage.removeItem('delay-reading'))
  await page.evaluate(key=>{const all=JSON.parse(localStorage.getItem('genoffice-pdf-view-state')??'{}');all[key]={page:-1,scale:'bad',frac:2,fitMode:'unknown'};localStorage.setItem('genoffice-pdf-view-state',JSON.stringify(all))},key(3));await open(3);assert.equal(Number(await zoom.inputValue()),1)
  await page.evaluate(()=>sessionStorage.setItem('block-reading','yes'));await page.reload();await page.waitForFunction(()=>document.querySelectorAll('.pdf-page').length===3&&document.querySelector('.pdf-page canvas'));assert.equal(Number(await zoom.inputValue()),1)
  const downloaded=Buffer.from(await page.evaluate(async()=>[...new Uint8Array(await(await fetch('/reports/v1/native/reading-fixture/3/api/file')).arrayBuffer())]));assert.deepEqual(downloaded,source)
  await page.evaluate(()=>sessionStorage.removeItem('block-reading'))
  await page.setViewportSize({width:1440,height:1200});await zoom.selectOption('0.5');await page.waitForFunction(()=>document.querySelector('.pdf-page-content')?.style.width==='190px');await scroll(0,0);await waitSaved({page:1,scale:.5,fitMode:null},3)
  await page.locator('.pdf-page-label').nth(1).click();await zoom.selectOption('0.67');await page.waitForFunction(()=>document.querySelector('.pdf-page-content')?.style.width==='254.60000000000002px'||Math.abs(parseFloat(document.querySelector('.pdf-page-content')?.style.width??'0')-254.6)<.01)
  await waitSaved({page:1,scale:.67,fitMode:null},3);assert.ok((await page.locator('.pdf-page.is-active').getAttribute('data-page-id')).endsWith(':page:1'))
  assert.ok((await page.locator('.pdf-thumbnail[aria-current="page"]').getAttribute('data-page-id')).endsWith(':page:1'))
  assert.deepEqual(errors,[])
  const evidence={ok:true,browserVersion:browser.version(),sourceSha256:sha(source),downloadedSha256:sha(downloaded),actualPreviewSha256:sha(previewBytes),customScaleAndFraction:saved,fitRecomputed:{before:fitted.scale,after:reopenedFit},afterReverse,sourceBeforePreview:beforePreview,pagehideFlush:flushed,delayedRestoreDoesNotOverwrite:true,scopeRevisionAndCorruptIsolation:true,readonlyAndUnavailableStorage:true,selectedPageSurvivesRefresh:true,userNavigationWinsDelayedRestore:true,draftOperations:draftBeforePreview,readingLifecycleTrace:await page.evaluate(()=>JSON.parse(sessionStorage.getItem('reading-trace')??'[]')),...await builtAssets(),provenance:'production static UI, real PDF.js and packed engine; delayed animation frames; substituted auth/revision routes; no desktop/production claim'}
  const dir=process.env.PDF_READING_EVIDENCE_DIR;if(dir){await mkdir(dir,{recursive:true});await writeFile(`${dir}/source.pdf`,source);await writeFile(`${dir}/preview.pdf`,previewBytes);await writeFile(`${dir}/downloaded.pdf`,downloaded);await writeFile(`${dir}/evidence.json`,JSON.stringify(evidence,null,2));await page.screenshot({path:`${dir}/reading.png`,fullPage:true})}
  console.log(JSON.stringify(evidence))
} catch(error) {
  const dir=process.env.PDF_READING_EVIDENCE_DIR
  if(dir&&browser){await mkdir(dir,{recursive:true});const page=browser.contexts()[0]?.pages()[0];if(page){await writeFile(`${dir}/failure.json`,JSON.stringify({error:String(error),state:await page.evaluate(()=>({text:document.body.innerText,storage:{...localStorage},trace:JSON.parse(sessionStorage.getItem('reading-trace')??'[]')}))},null,2));await page.screenshot({path:`${dir}/failure.png`,fullPage:true})}}
  throw error
} finally {await browser?.close();server.kill('SIGTERM')}
