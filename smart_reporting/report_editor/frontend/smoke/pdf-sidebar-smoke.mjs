import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { mkdir, writeFile, readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { observePdfBuiltAssets } from './pdf-object-dialog-checks.mjs'
import { inspectPdfNavigation } from './pdf-navigation-checks.mjs'
import { inspectPdfSidebarKeys } from './pdf-gesture-keyboard-checks.mjs'
const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.PDF_SIDEBAR_SMOKE_PORT ?? 4211), base = `http://127.0.0.1:${port}`, sha = bytes => createHash('sha256').update(bytes).digest('hex')
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
 w=PdfWriter(clone_from=PdfReader(BytesIO(size_fixture())))
 for i in range(27):w.add_blank_page(400,500)
 w.add_outline_item('Second page',1)
 if p.get('navigation'):
  parent=w.add_outline_item('章节导航 '+ '很长的目录标题'.__mul__(6),0)
  for i in range(12):parent=w.add_outline_item('子章节 '+str(i+1)+' · '+'完整目录标题'.__mul__(4),i+2,parent=parent)
  w.add_metadata({'/Title':'桌面属性与导航核验 · '+'长标题'.__mul__(40),'/Author':'导航测试作者','/Subject':'长属性不裁切','/Keywords':'PC,PDF,导航'})
 out=BytesIO();w.write(out);b=out.getvalue();print(json.dumps({'bytes':base64.b64encode(b).decode(),'model':inspect_pdf(b)}))
elif p['mode']=='inspect':print(json.dumps(inspect_pdf(base64.b64decode(p['bytes']))))
elif p['mode']=='patch':
 b=base64.b64decode(p['bytes']);r=patch_pdf_with_receipt(b,p['operations']);r['bytes']=base64.b64encode(r.pop('content')).decode();r['model']=inspect_pdf(base64.b64decode(r['bytes']));print(json.dumps(r))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw Error(result.stderr)
  return JSON.parse(result.stdout)
}
const fixture = python({ mode: 'create', navigation:!!process.env.PDF_NAVIGATION_VIEWPORTS }), source = Buffer.from(fixture.bytes, 'base64'), revisions = new Map([[1, source], [2, source]])
let browser, readonly = false, savedOperations, previewBytes
const server = spawn('./node_modules/.bin/vite', ['preview', ...(process.env.PDF_SMOKE_VITE_CONFIG?['--config',process.env.PDF_SMOKE_VITE_CONFIG]:[]), '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
try {
  for (let n = 0; n < 100; n++) { try { if ((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{}) })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor:2, acceptDownloads: true }), errors = []
  const builtAssets=await observePdfBuiltAssets(page),navigationLayouts=[]
  page.on('pageerror', error => errors.push(error.message)); page.on('console', entry => { if (entry.type() === 'error') errors.push(entry.text()) })
  await page.addInitScript(() => {
    const get=Storage.prototype.getItem,set=Storage.prototype.setItem,key='genoffice-pdf-sidebar-width'
    window.__rawSidebar=()=>get.call(localStorage,key)
    Storage.prototype.getItem=function(k){if(k===key&&sessionStorage.getItem('block-sidebar')==='yes')throw Error('fixture preference denied');return get.call(this,k)}
    Storage.prototype.setItem=function(k,v){if(k===key&&sessionStorage.getItem('block-sidebar')==='yes')throw Error('fixture preference quota');return set.call(this,k,v)}
    document.addEventListener('pointerdown',event=>{if(event.target.closest?.('[aria-label="调整 PDF 侧栏宽度"]'))window.__sidebarPointer=event.pointerId},true)
  })
  const revision = route => Number(route.request().url().match(/sidebar-fixture\/(\d+)\/api/)[1]), active = route => revisions.get(revision(route))
  const inspect = bytes => python({ mode: 'inspect', bytes: bytes.toString('base64') }), patch = (bytes, operations) => python({ mode: 'patch', bytes: bytes.toString('base64'), operations })
  await page.route('**/reports/v1/native/sidebar-fixture/*/api/context', route => route.fulfill({ json: {
    context: { documentId: 'sidebar-fixture', revision: revision(route), parentRevision: null, format: 'pdf', origin: 'upload', scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' }, sourceFile: { path: 'attachments.pdf', size: active(route).length, sha256: sha(active(route)), mediaType: 'application/pdf' } }, csrfToken: 'fixture', capabilities: { pdf_editor: true }, editingEnabled: !readonly,
  } }))
  await page.route('**/reports/v1/native/sidebar-fixture/*/api/file', route => route.fulfill({ body: active(route), contentType: 'application/pdf' }))
  await page.route('**/reports/v1/native/sidebar-fixture/*/api/preview', route => {
    const bytes = active(route), ops = route.request().postDataJSON().operations, result = ops.length ? patch(bytes,ops) : null
    return route.fulfill({ json: { sourceSha256: sha(bytes), model: result?.model ?? inspect(bytes), appliedOperationIndices: result?.appliedOperationIndices ?? [], skippedOperations: [], previewDigest: result?.previewDigest } })
  })
  await page.route('**/reports/v1/native/sidebar-fixture/*/api/preview.pdf', route => {
    const input = route.request().postDataJSON(), result = patch(active(route),input.operations); previewBytes=Buffer.from(result.bytes,'base64'); assert.equal(input.expectedPreviewDigest,result.previewDigest)
    return route.fulfill({ body: Buffer.from(result.bytes,'base64'), contentType:'application/pdf', headers: { 'X-Native-Preview-Digest':result.previewDigest } })
  })
  await page.route(/\/reports\/v1\/native\/sidebar-fixture\/[123]$/, async route => route.fulfill({ response: await route.fetch({ url:`${base}/reports/v1/editor/assets/native.html` }) }))
  const key='genoffice-pdf-sidebar-width',divider=page.getByRole('separator',{name:'调整 PDF 侧栏宽度'}),thumbs=page.getByRole('navigation',{name:'页面缩略图及顺序'}),firstThumb=thumbs.locator('canvas').first()
  const open=async n=>{await page.goto(`${base}/reports/v1/native/sidebar-fixture/${n}`);await page.waitForFunction(()=>document.querySelectorAll('.pdf-page').length===30&&document.querySelector('.pdf-page canvas'),null,{timeout:60000});await page.waitForFunction(()=>document.querySelector('.pdf-thumbnail canvas')?.width>1)}
  const frames=()=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))
  const paneWidth=()=>page.evaluate(()=>[...document.querySelectorAll('.pdf-layout > nav,.pdf-layout > aside')].find(p=>!p.hidden).getBoundingClientRect().width)
  const pref=()=>page.evaluate(()=>window.__rawSidebar())
  const ops=()=>page.evaluate(()=>Object.entries(localStorage).filter(([k])=>k.startsWith('native-editor-draft')).map(([,v])=>JSON.parse(v).operations))
  const waitWidth=w=>page.waitForFunction(w=>{const p=[...document.querySelectorAll('.pdf-layout > nav,.pdf-layout > aside')].find(p=>!p.hidden);return p&&Math.abs(p.getBoundingClientRect().width-w)<1},w)
  const waitRaster=w=>page.waitForFunction(w=>{const c=document.querySelector('.pdf-thumbnail canvas');return c&&Math.abs(c.width-w)<2},w)
  const begin=async()=>{const b=await divider.boundingBox();await page.mouse.move(b.x+b.width/2,b.y+80);await page.mouse.down();return {x:b.x+b.width/2,y:b.y+80}}
  const fit=async()=>page.waitForFunction(()=>{const v=document.querySelector('.pdf-document-pages');if(!v)return false;const s=getComputedStyle(v),w=v.clientWidth-parseFloat(s.paddingLeft)-parseFloat(s.paddingRight),rows=[...v.querySelectorAll('.pdf-page-row')];const max=Math.max(...rows.map(r=>r.getBoundingClientRect().width));return max<=w+1&&Math.abs(max-w)<1.5})
  await open(1)
  const gestureKeyboard=process.env.PDF_GESTURE_KEYBOARD==='1'?await inspectPdfSidebarKeys(page,{operations:ops,directory:process.env.PDF_SIDEBAR_EVIDENCE_DIR}):[]
  if(process.env.PDF_NAVIGATION_VIEWPORTS){navigationLayouts.push(...await inspectPdfNavigation(page,{operations:ops,directory:process.env.PDF_SIDEBAR_EVIDENCE_DIR,phase:'editable',fileSize:source.length}));await open(1)}
  assert.equal(await paneWidth(),150);assert.equal(await divider.getAttribute('aria-valuemin'),'120');assert.equal(await divider.getAttribute('aria-valuemax'),'320')
  assert.equal(await thumbs.locator('canvas').last().evaluate(c=>c.width),1)
  const lazyInitial=await thumbs.locator('canvas').evaluateAll(nodes=>({total:nodes.length,rasterized:nodes.filter(n=>n.width>1).length}));assert.ok(lazyInitial.rasterized<15)
  await page.evaluate(()=>{window.__firstSidebarThumb=document.querySelector('.pdf-thumbnail canvas');document.body.style.cursor='crosshair';document.body.style.userSelect='text'})
  const initialRaster=await firstThumb.evaluate(c=>c.width),start=await begin();await page.mouse.move(start.x+80,start.y,{steps:6});await waitWidth(230);await frames()
  assert.equal(await firstThumb.evaluate(c=>c===window.__firstSidebarThumb),true);assert.equal(await firstThumb.evaluate(c=>c.width),initialRaster);assert.equal(await pref(),null)
  await page.mouse.up();await waitRaster((230-25)*2);assert.equal(await pref(),'230');assert.equal(await page.evaluate(()=>document.body.style.cursor),'crosshair');assert.equal(await page.evaluate(()=>document.body.style.userSelect),'text')
  const committedRaster=await firstThumb.evaluate(c=>c.width)
  const cancelStart=await begin();await page.mouse.move(cancelStart.x+50,cancelStart.y);await waitWidth(280);await page.keyboard.press('Escape');await page.mouse.up();await waitWidth(230);assert.equal(await pref(),'230')
  const pointerCancel=await begin();await page.mouse.move(pointerCancel.x-40,pointerCancel.y);await waitWidth(190);await page.evaluate(()=>window.dispatchEvent(new PointerEvent('pointercancel',{pointerId:window.__sidebarPointer})));await page.mouse.up();await waitWidth(230);assert.equal(await pref(),'230')
  const blurStart=await begin();await page.mouse.move(blurStart.x+20,blurStart.y);await frames();await page.evaluate(()=>window.dispatchEvent(new Event('blur')));await page.mouse.up();await waitWidth(230)
  await divider.focus();await divider.press('End');await waitWidth(320);assert.equal(await pref(),'320');await divider.press('Home');await waitWidth(120);await divider.press('ArrowRight');await waitWidth(130);await divider.press('ArrowLeft');await waitWidth(120)
  const capped=await begin();await page.mouse.move(capped.x+500,capped.y);await page.mouse.up();await waitWidth(320);assert.equal(await pref(),'320')
  // Commit an exact260px preference before testing all mutually exclusive panels.
  const exact=await begin();await page.mouse.move(exact.x-60,exact.y);await page.mouse.up();await waitWidth(260);assert.equal(await pref(),'260')
  await page.locator('[data-pdf-ribbon-tab="view"]').click()
  const expectedPanels=[['outline','.pdf-outline'],['comments','.pdf-comments-sidebar'],['attachments','.pdf-attachments-sidebar'],['thumbnails','.pdf-thumbnails']]
  for(const [id,selector] of expectedPanels){await page.locator(`[data-source-command-id="genoffice.pdf.view.navigation.${id}"]`).click();await waitWidth(260);assert.equal(await divider.getAttribute('aria-controls'),await page.locator(selector).getAttribute('id'))}
  await page.locator('[data-source-command-id="genoffice.pdf.view.navigation.thumbnails"]').click();assert.equal(await divider.isVisible(),false);await page.locator('[data-source-command-id="genoffice.pdf.view.navigation.thumbnails"]').click();await waitWidth(260)
  const switched=await begin();await page.mouse.move(switched.x+20,switched.y);await frames();await page.locator('[data-source-command-id="genoffice.pdf.view.navigation.comments"]').evaluate(b=>b.click());await page.mouse.up();await waitWidth(260);assert.equal(await pref(),'260');await page.locator('[data-source-command-id="genoffice.pdf.view.navigation.thumbnails"]').click()
  await page.locator('[data-source-command-id="genoffice.pdf.view.pageZoom.fitWidth"]').click();await fit()
  await page.setViewportSize({width:390,height:900});await waitWidth(156);await fit();assert.equal(await pref(),'260');assert.equal(await divider.getAttribute('aria-valuemax'),'156')
  await page.setViewportSize({width:1440,height:1000});await waitWidth(156);await page.reload();await page.waitForFunction(()=>document.querySelectorAll('.pdf-page').length===30);await waitWidth(260);await fit();assert.deepEqual(await ops(),[])
  await page.locator('[data-pdf-ribbon-tab="annotate"]').click();await page.locator('[data-source-command-id="genoffice.pdf.annotate.drawTools.note"]').click();await page.getByLabel('文字批注内容').fill('sidebar preview note');await page.locator('.pdf-page-content').first().scrollIntoViewIfNeeded();await page.waitForFunction(()=>document.querySelector('.pdf-page-content')?.onpointerup);await page.locator('.pdf-page-content').first().click({position:{x:100,y:80}});await page.waitForFunction(()=>document.querySelectorAll('.pdf-pending-note').length===1)
  await thumbs.locator('canvas').last().scrollIntoViewIfNeeded();await page.waitForFunction(()=>[...document.querySelectorAll('.pdf-thumbnail canvas')].at(-1)?.width>1);await page.evaluate(()=>window.__deletedSidebarThumb=[...document.querySelectorAll('.pdf-thumbnail canvas')].at(-1))
  await page.waitForFunction(()=>document.querySelector('.pdf-thumbnail canvas')?.width===1)
  await page.locator('.pdf-page-label').last().click();await page.locator('[data-pdf-ribbon-tab="page"]').click();await page.locator('[data-source-command-id="genoffice.pdf.page.delete"]').click();await page.waitForFunction(()=>document.querySelectorAll('.pdf-page').length===29&&window.__deletedSidebarThumb.width===1)
  await thumbs.evaluate(p=>{p.scrollTop=0});await page.waitForFunction(()=>document.querySelector('.pdf-thumbnail canvas')?.width>1);await page.evaluate(()=>window.__sourceSidebarThumb=document.querySelector('.pdf-thumbnail canvas'))
  const beforePreview=await ops();assert.deepEqual(beforePreview[0].map(op=>op.kind),['addTextAnnotation','deletePage','reorderPages'])
  await page.locator('[data-pdf-ribbon-tab="edit"]').click();await page.getByRole('button',{name:'校验当前修改',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.native-pdf-editor')?.dataset.pdfPreview==='true'&&[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='返回原稿编辑'&&!b.disabled))
  await page.waitForFunction(()=>document.querySelector('.pdf-thumbnail canvas')?.width>1);assert.ok(await firstThumb.evaluate(c=>c!==window.__sourceSidebarThumb))
  await divider.focus();await divider.press('ArrowLeft');await waitWidth(250);await page.waitForFunction(()=>Math.abs((document.querySelector('.pdf-thumbnail canvas')?.width??0)-450)<2)
  await page.getByRole('button',{name:'返回原稿编辑',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.native-pdf-editor')?.dataset.pdfPreview==='false'&&document.querySelectorAll('.pdf-page').length===29);await page.waitForFunction(()=>document.querySelector('.pdf-thumbnail canvas')?.width>1);assert.deepEqual(await ops(),beforePreview)
  const downloaded=Buffer.from(await page.evaluate(async()=>[...new Uint8Array(await(await fetch('/reports/v1/native/sidebar-fixture/1/api/file')).arrayBuffer())]));assert.deepEqual(downloaded,source)
  readonly=true;await open(2);await waitWidth(250);await divider.focus();await divider.press('ArrowRight');await waitWidth(260)
  if(process.env.PDF_NAVIGATION_VIEWPORTS){navigationLayouts.push(...await inspectPdfNavigation(page,{operations:ops,directory:process.env.PDF_SIDEBAR_EVIDENCE_DIR,phase:'readonly',fileSize:source.length}));await open(2);await waitWidth(260)}
  await page.evaluate(()=>localStorage.setItem('genoffice-pdf-sidebar-width','not-a-number'));await page.reload();await page.waitForFunction(()=>document.querySelectorAll('.pdf-page').length===30);await waitWidth(150)
  await page.evaluate(()=>sessionStorage.setItem('block-sidebar','yes'));await page.reload();await page.waitForFunction(()=>document.querySelectorAll('.pdf-page').length===30);await waitWidth(150);await divider.focus();await divider.press('ArrowRight');await waitWidth(160);assert.equal(await pref(),'not-a-number')
  assert.ok(await page.evaluate(()=>Object.entries(localStorage).filter(([k])=>k.startsWith('native-editor-draft')).map(([,v])=>JSON.parse(v)).filter(d=>d.identity.revision===2).every(d=>d.operations.length===0)))
  await page.evaluate(()=>{document.body.style.cursor='help';document.body.style.userSelect='text'});const closing=await begin();await page.mouse.move(closing.x+20,closing.y);await frames();await page.evaluate(()=>window.dispatchEvent(new Event('pagehide')));await page.mouse.up();await frames();assert.equal(await page.locator('.pdf-page').count(),0);assert.equal(await page.evaluate(()=>document.body.style.cursor),'help');assert.equal(await page.evaluate(()=>document.body.style.userSelect),'text');assert.deepEqual(errors,[])
  const evidence={ok:true,gestureKeyboard,browserVersion:browser.version(),sourceSha256:sha(source),downloadedSha256:sha(downloaded),previewSha256:sha(previewBytes),initialWidth:150,committedWidth:260,initialRaster,committedRaster,lazyInitial,dragDoesNotReraster:true,cancelPointerEscapeBlurAndSwitch:true,keyboardAndBounds:true,mobileClampDoesNotPersist:true,readonlyCorruptAndDeniedStorage:true,documentCachesIsolated:true,offscreenAndDeletedBitmapsReleased:true,activeDragDisposeRestoresStyles:true,operations:beforePreview[0],navigationLayouts,...await builtAssets(),provenance:'production static UI; actual PDF.js/packed engine; real mouse/keyboard and pointer cancellation; substituted auth/revision routes; no desktop/production claim'}
  const dir=process.env.PDF_SIDEBAR_EVIDENCE_DIR;if(dir){await mkdir(dir,{recursive:true});await writeFile(`${dir}/source.pdf`,source);await writeFile(`${dir}/preview.pdf`,previewBytes);await writeFile(`${dir}/downloaded.pdf`,downloaded);await writeFile(`${dir}/evidence.json`,JSON.stringify(evidence,null,2))}
  console.log(JSON.stringify(evidence))
} catch(error){const dir=process.env.PDF_SIDEBAR_EVIDENCE_DIR;if(dir&&browser){await mkdir(dir,{recursive:true});const page=browser.contexts()[0]?.pages()[0];if(page){await writeFile(`${dir}/failure.json`,JSON.stringify({error:String(error),state:await page.evaluate(()=>({text:document.body.innerText,pref:window.__rawSidebar?.(),sidebar:[...document.querySelectorAll('.pdf-layout>nav,.pdf-layout>aside')].map(p=>({hidden:p.hidden,width:p.getBoundingClientRect().width})),storage:{...localStorage}}))},null,2));await page.screenshot({path:`${dir}/failure.png`,fullPage:true})}};throw error
} finally {await browser?.close();server.kill('SIGTERM')}
