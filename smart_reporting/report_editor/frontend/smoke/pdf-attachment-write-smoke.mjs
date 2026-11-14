import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { mkdir, writeFile, readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { observePdfBuiltAssets } from './pdf-object-dialog-checks.mjs'
import { inspectPdfSidebar } from './pdf-sidebar-checks.mjs'
const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.PDF_ATTACHMENTS_SMOKE_PORT ?? 4212), base = `http://127.0.0.1:${port}`, sha = bytes => createHash('sha256').update(bytes).digest('hex')
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
 b=size_fixture();w=PdfWriter(clone_from=PdfReader(BytesIO(b)))
 files={'folderA/same.txt':b'first attachment', 'folderB/same.txt':b'second attachment', 'empty.bin':b'', '报告.bin':bytes(range(256))*300}
 for name,data in files.items():
  embedded=w.add_attachment(name,data);embedded.description=TextStringObject('<img src=x onerror=alert(1)> '+name)
 out=BytesIO();w.write(out);b=out.getvalue();print(json.dumps({'bytes':base64.b64encode(b).decode(),'empty':base64.b64encode(size_fixture()).decode(),'model':inspect_pdf(b),'files':{name:base64.b64encode(data).decode() for name,data in files.items()}}))
elif p['mode']=='inspect':print(json.dumps(inspect_pdf(base64.b64decode(p['bytes']))))
elif p['mode']=='patch':
 b=base64.b64decode(p['bytes']);r=patch_pdf_with_receipt(b,p['operations']);r['bytes']=base64.b64encode(r.pop('content')).decode();r['model']=inspect_pdf(base64.b64decode(r['bytes']));print(json.dumps(r))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw Error(result.stderr)
  return JSON.parse(result.stdout)
}
const fixture = python({ mode: 'create' }), source = Buffer.from(fixture.bytes, 'base64'), revisions = new Map([[1, source], [3, Buffer.from(fixture.empty, 'base64')]])
let page, browser, readonly = false, savedOperations
const server = spawn('./node_modules/.bin/vite', ['preview', ...(process.env.PDF_STATIC_ROOT?['--outDir',process.env.PDF_STATIC_ROOT]:[]), '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
try {
  for (let n = 0; n < 100; n++) { try { if ((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? {executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE} : {}) })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true }); page = await context.newPage(); const errors = []
  const verifyAssets=await observePdfBuiltAssets(page),sidebarLayouts=[]
  page.on('pageerror', error => errors.push(error.message)); page.on('console', entry => { if (entry.type() === 'error') errors.push(entry.text()) })
  await page.addInitScript(() => {
    window.__attachmentReads = []; window.__failList = true; window.__failContent = true; window.__releasedAttachments = false; window.__downloads = 0; window.__liveUrls = new Set()
    const create = URL.createObjectURL, revoke = URL.revokeObjectURL
    URL.createObjectURL = function(blob) { const url = create.call(this,blob); if (blob.type === 'application/octet-stream') { window.__downloads++; window.__liveUrls.add(url) }; return url }
    URL.revokeObjectURL = function(url) { window.__liveUrls.delete(url); return revoke.call(this,url) }
    const original = Worker.prototype.postMessage
    Worker.prototype.postMessage = function(message, ...args) {
      if (['GetAttachments','GetAttachmentContent'].includes(message?.action)) {
        window.__attachmentReads.push({ doc: message.sourceName, action: message.action, id: message.data })
        if ((message.action === 'GetAttachments' && window.__failList) || (message.action === 'GetAttachmentContent' && window.__failContent)) {
          if (message.action === 'GetAttachments') window.__failList = false; else window.__failContent = false
          queueMicrotask(() => this.dispatchEvent(new MessageEvent('message', { data: { sourceName: message.targetName, targetName: message.sourceName, callback: 2, callbackId: message.callbackId, reason: { name: 'UnknownErrorException', message: 'fixture attachment read failed', details: 'test fault' } } }))); return
        }
        if (message.action === 'GetAttachments' && !window.__releasedAttachments) { const release = () => { window.__releasedAttachments = true; original.call(this,message,...args) }; if (location.pathname.endsWith('/1')) window.__releaseAttachmentRead = release; else setTimeout(release,150); return }
      }
      return original.call(this,message,...args)
    }
  })
  const revision = route => Number(route.request().url().match(/attachments-fixture\/(\d+)\/api/)[1]), active = route => revisions.get(revision(route))
  const inspect = bytes => python({ mode: 'inspect', bytes: bytes.toString('base64') }), patch = (bytes, operations) => python({ mode: 'patch', bytes: bytes.toString('base64'), operations })
  await page.route('**/reports/v1/native/attachments-fixture/*/api/context', route => route.fulfill({ json: {
    context: { documentId: 'attachments-fixture', revision: revision(route), parentRevision: null, format: 'pdf', origin: 'upload', scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' }, sourceFile: { path: 'attachments.pdf', size: active(route).length, sha256: sha(active(route)), mediaType: 'application/pdf' } }, csrfToken: 'fixture', capabilities: { pdf_editor: true }, editingEnabled: !readonly,
  } }))
  await page.route('**/reports/v1/native/attachments-fixture/*/api/file', route => route.fulfill({ body: active(route), contentType: 'application/pdf' }))
  await page.route('**/reports/v1/native/attachments-fixture/*/api/preview', route => {
    const bytes = active(route), ops = route.request().postDataJSON().operations, result = ops.length ? patch(bytes,ops) : null
    return route.fulfill({ json: { sourceSha256: sha(bytes), model: result?.model ?? inspect(bytes), appliedOperationIndices: result?.appliedOperationIndices ?? [], skippedOperations: [], previewDigest: result?.previewDigest } })
  })
  await page.route('**/reports/v1/native/attachments-fixture/*/api/preview.pdf', route => {
    const input = route.request().postDataJSON(), result = patch(active(route),input.operations); assert.equal(input.expectedPreviewDigest,result.previewDigest)
    return route.fulfill({ body: Buffer.from(result.bytes,'base64'), contentType:'application/pdf', headers: { 'X-Native-Preview-Digest':result.previewDigest } })
  })
  await page.route('**/reports/v1/native/attachments-fixture/*/api/save', route => {
    const input = route.request().postDataJSON(), result = patch(active(route),input.operations); savedOperations = input.operations; const bytes = Buffer.from(result.bytes,'base64'); revisions.set(2,bytes)
    return route.fulfill({ json: { documentId:'attachments-fixture',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{pdf:{downloadUrl:'/attachment-result.pdf',size:bytes.length,sha256:sha(bytes)}},editor:{openUrl:'/reports/v1/native/attachments-fixture/2'},validation:{ok:false,issues:[{code:'manual_review',message:'下载仍可用'}]} } })
  })
  await page.route('**/attachment-result.pdf', route => route.fulfill({ body:revisions.get(2),contentType:'application/pdf' }))
  await page.route(/\/reports\/v1\/native\/attachments-fixture\/[123]$/, async route => route.fulfill({ response: await route.fetch({ url:`${base}/reports/v1/editor/assets/native.html` }) }))
  const open = async n => { await page.goto(`${base}/reports/v1/native/attachments-fixture/${n}`); await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 3 && document.querySelector('.pdf-page canvas'),null,{timeout:60000}) }
  const ops = () => page.evaluate(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.includes('attachments-fixture'))?.[1] ?? '{"operations":[]}').operations)
  const panel = page.getByRole('complementary',{name:'PDF 附件'}), toggle = page.locator('[data-source-command-id="genoffice.pdf.view.navigation.attachments"]'), rows = panel.locator('li')
  const loaded = () => page.waitForFunction(() => !document.querySelector('.pdf-attachments-sidebar [role="status"]')?.textContent?.includes('正在读取'))
  await open(1); await page.locator('[data-pdf-ribbon-tab="view"]').click(); await toggle.click(); await loaded()
  assert.match(await panel.locator('[role="status"]').innerText(),/目录读取失败/); assert.equal(await rows.count(),0)
  sidebarLayouts.push(...await inspectPdfSidebar(page,{panel,kind:'attachments',phase:'directory-error',operations:ops,directory:process.env.PDF_ATTACHMENTS_EVIDENCE_DIR}))
  await panel.getByRole('button',{name:'重试附件读取'}).click(); await page.waitForFunction(() => window.__attachmentReads.length === 2); await toggle.click(); assert.equal(await panel.isVisible(),false); await page.evaluate(()=>window.__releaseAttachmentRead()); await toggle.click(); await loaded()
  assert.match(await panel.locator('[role="status"]').innerText(),/1 个内容读取失败/); assert.equal(await rows.count(),4)
  assert.equal(await rows.getByRole('button',{name:'下载附件'}).filter({visible:true}).count(),4)
  sidebarLayouts.push(...await inspectPdfSidebar(page,{panel,kind:'attachments',phase:'content-error',operations:ops,directory:process.env.PDF_ATTACHMENTS_EVIDENCE_DIR}))
  const retry=panel.getByRole('button',{name:'重试附件读取'});if(process.env.PDF_ATTACHMENTS_KEYBOARD==='1'){await retry.focus();await page.keyboard.press('Space')}else await retry.click(); await loaded(); assert.equal(await panel.getByRole('button',{name:'下载附件',disabled:true}).count(),0)
  if(process.env.PDF_ATTACHMENTS_KEYBOARD==='1')assert.equal(await rows.locator('[data-pdf-attachment-action=download]').first().evaluate(node=>document.activeElement===node),true)
  sidebarLayouts.push(...await inspectPdfSidebar(page,{panel,kind:'attachments',phase:'loaded',operations:ops,directory:process.env.PDF_ATTACHMENTS_EVIDENCE_DIR,reopen:async()=>{await toggle.click();await loaded()}}))
  const reads = await page.evaluate(() => window.__attachmentReads); assert.equal(reads.filter(r => r.action === 'GetAttachments').length,2); assert.equal(reads.filter(r => r.action === 'GetAttachmentContent').length,5)
  assert.equal(await rows.locator('strong').filter({hasText:/^same.txt$/}).count(),2); assert.equal(await panel.locator('img').count(),0)
  let expected = Object.values(fixture.files).map(b => sha(Buffer.from(b,'base64'))).sort(), downloads=[]
  const downloadRow = async n => { const event = page.waitForEvent('download'); await rows.nth(n).getByRole('button',{name:'下载附件'}).click(); const download = await event; const bytes=await readFile(await download.path()); return {name:download.suggestedFilename(),bytes} }
  for(let n=0;n<4;n++){ const result=await downloadRow(n); downloads.push({name:result.name,sha256:sha(result.bytes),size:result.bytes.length}) }
  assert.deepEqual(downloads.map(r=>r.sha256).sort(),expected); assert.ok(downloads.some(r=>r.size===0)); assert.ok(downloads.every(r=>!/[\\/]/.test(r.name)))
  await page.evaluate(() => window.__oldAttachment=document.querySelector('.pdf-attachments-list button')); const before=await ops(), beforeCount=await page.evaluate(()=>window.__downloads)
  await toggle.click(); await page.evaluate(()=>window.__oldAttachment.click()); assert.equal(await page.evaluate(()=>window.__downloads),beforeCount)
  await toggle.click(); await loaded(); assert.deepEqual(await page.evaluate(()=>window.__attachmentReads),reads)
  await page.locator('[data-source-command-id="genoffice.pdf.view.navigation.comments"]').click(); assert.equal(await panel.isVisible(),false); await toggle.click(); await loaded()
  await page.locator('[data-pdf-ribbon-tab="annotate"]').click(); await page.locator('[data-source-command-id="genoffice.pdf.annotate.drawTools.note"]').click(); await page.getByLabel('文字批注内容').fill('attachment preservation note'); await page.locator('.pdf-page-content').first().click({position:{x:120,y:90}}); await page.waitForFunction(()=>document.querySelectorAll('.pdf-pending-note').length===1); await loaded()
  const withNote=await ops(); assert.equal(withNote.length,1); assert.deepEqual(before,[])
  assert.equal(fixture.model.attachmentsEditable,true,fixture.model.attachmentsReason)
  const removedKey = fixture.model.attachments.find(row=>row.name.includes('same.txt')).key
  const remove=rows.filter({hasText:'same.txt'}).first().locator('[data-pdf-attachment-action=remove]');if(process.env.PDF_ATTACHMENTS_KEYBOARD==='1'){await remove.focus();await page.keyboard.press('Space')}else await remove.click(); await loaded()
  if(process.env.PDF_ATTACHMENTS_KEYBOARD==='1')assert.equal(await rows.filter({hasText:'same.txt'}).first().locator('[data-pdf-attachment-action=remove]').evaluate(node=>document.activeElement===node&&node.textContent==='撤销移除附件'),true)
  assert.equal((await ops()).filter(op=>op.kind==='removeAttachment').length,1)
  await page.locator('[data-pdf-ribbon-tab="home"]').click()
  await page.getByRole('button',{name:'撤销',exact:true}).click(); await loaded(); assert.equal((await ops()).length,1)
  await page.getByRole('button',{name:'重做',exact:true}).click(); await loaded()
  const upload = page.getByLabel('选择新增附件'), addedBytes=Buffer.from([0,1,2,255,128,10])
  await upload.setInputFiles({name:'zz-new.bin',mimeType:'application/octet-stream',buffer:addedBytes})
  await page.waitForFunction(()=>document.querySelector('.pdf-attachments-list')?.textContent.includes('zz-new.bin（待新增）'))
  if(process.env.PDF_ATTACHMENTS_KEYBOARD==='1'){
    const cancel=rows.locator('[data-pdf-attachment-action=cancel]');await cancel.focus();await page.keyboard.press('Space');await loaded()
    assert.equal(await cancel.count(),0);assert.equal(await panel.getByRole('button',{name:'新增附件',exact:true}).evaluate(node=>document.activeElement===node),true)
    await upload.setInputFiles({name:'zz-new.bin',mimeType:'application/octet-stream',buffer:addedBytes});await page.waitForFunction(()=>document.querySelector('.pdf-attachments-list')?.textContent.includes('zz-new.bin（待新增）'))
  }
  const withAttachments=await ops(); assert.equal(withAttachments.length,3)
  sidebarLayouts.push(...await inspectPdfSidebar(page,{panel,kind:'attachments',phase:'pending',operations:ops,directory:process.env.PDF_ATTACHMENTS_EVIDENCE_DIR}))
  await page.evaluate(()=>{const original=File.prototype.arrayBuffer;window.__restoreFileRead=()=>File.prototype.arrayBuffer=original;File.prototype.arrayBuffer=function(){return this.name==='stale.bin'?new Promise(resolve=>window.__releaseFile=()=>original.call(this).then(resolve)):original.call(this)}})
  await upload.setInputFiles({name:'stale.bin',mimeType:'application/octet-stream',buffer:Buffer.from('stale')}); await page.waitForFunction(()=>!!window.__releaseFile)
  await page.getByRole('button',{name:'撤销',exact:true}).click();await loaded();await page.evaluate(()=>window.__releaseFile());await page.waitForFunction(()=>document.body.textContent.includes('草稿已变化，请重新选择附件'))
  assert.equal((await ops()).some(op=>op.name==='stale.bin'),false)
  await page.evaluate(()=>window.__restoreFileRead());await page.getByRole('button',{name:'重做',exact:true}).click();await loaded();assert.deepEqual(await ops(),withAttachments)
  await upload.setInputFiles({name:'zz-new.bin',mimeType:'application/octet-stream',buffer:Buffer.from('duplicate')})
  await page.waitForFunction(()=>document.body.textContent.includes('附件名称无效或重复'))
  assert.deepEqual(await ops(),withAttachments)
  expected=Object.entries(fixture.files).filter(([key])=>key!==removedKey).map(([,b])=>sha(Buffer.from(b,'base64'))).concat(sha(addedBytes)).sort()
  await page.reload(); await page.waitForFunction(()=>document.querySelector('.pdf-page canvas'),null,{timeout:60000})
  await page.evaluate(()=>{window.__failList=false;window.__failContent=false;window.__releasedAttachments=true})
  await page.locator('[data-pdf-ribbon-tab="view"]').click(); if(!await panel.isVisible())await toggle.click(); await loaded()
  assert.deepEqual(await ops(),withAttachments);assert.equal(await panel.getByRole('button',{name:'撤销移除附件'}).count(),1)
  await page.evaluate(()=>window.__oldAttachment=document.querySelector('.pdf-attachments-list button'))
  await page.locator('[data-pdf-ribbon-tab="edit"]').click(); await page.getByRole('button',{name:'校验当前修改',exact:true}).click(); await page.waitForFunction(()=>document.querySelector('.native-pdf-editor')?.dataset.pdfPreview==='true'); await loaded()
  const count=await page.evaluate(()=>window.__downloads); await page.evaluate(()=>window.__oldAttachment.click()); assert.equal(await page.evaluate(()=>window.__downloads),count)
  assert.equal(await rows.count(),4); assert.ok(expected.includes(sha((await downloadRow(0)).bytes)))
  assert.ok(new Set((await page.evaluate(()=>window.__attachmentReads)).map(r=>r.doc)).size>=2)
  await page.getByRole('button',{name:'返回原稿编辑',exact:true}).click(); await loaded(); assert.deepEqual(await ops(),withAttachments)
  await page.locator('[data-action="save"]').click(); await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存修订 2',null,{timeout:30000})
  const downloaded=Buffer.from(await page.evaluate(async()=>[...new Uint8Array(await(await fetch('/attachment-result.pdf')).arrayBuffer())])); assert.deepEqual(downloaded,revisions.get(2))
  readonly=true; await open(2); await page.locator('[data-pdf-ribbon-tab="view"]').click(); await toggle.click(); await loaded(); if(await panel.getByRole('button',{name:'重试附件读取'}).isVisible()){await panel.getByRole('button',{name:'重试附件读取'}).click();await loaded()}; if(await panel.getByRole('button',{name:'重试附件读取'}).isVisible()){await panel.getByRole('button',{name:'重试附件读取'}).click();await loaded()}
  assert.equal(await rows.count(),4); assert.ok(expected.includes(sha((await downloadRow(3)).bytes))); assert.equal(await panel.getByRole('button',{name:'新增附件',exact:true}).isDisabled(),true); assert.equal(await panel.locator('[data-pdf-attachment-action=remove]:enabled').count(),0)
  sidebarLayouts.push(...await inspectPdfSidebar(page,{panel,kind:'attachments',phase:'readonly',operations:ops,directory:process.env.PDF_ATTACHMENTS_EVIDENCE_DIR}))
  await page.setViewportSize({width:390,height:844}); assert.ok(await panel.getByRole('button',{name:'关闭附件侧栏'}).isVisible()); await panel.getByRole('button',{name:'关闭附件侧栏'}).click(); assert.equal(await panel.isVisible(),false)
  await open(3); await page.evaluate(()=>window.__failList=false); await page.locator('[data-pdf-ribbon-tab="view"]').click(); await toggle.click(); await loaded(); assert.equal(await rows.count(),0); assert.match(await panel.locator('[role="status"]').innerText(),/没有附件/)
  sidebarLayouts.push(...await inspectPdfSidebar(page,{panel,kind:'attachments',phase:'empty',operations:ops,directory:process.env.PDF_ATTACHMENTS_EVIDENCE_DIR}))
  assert.deepEqual(errors,[])
  const evidence={attachmentWrite:true,staleFileReadRejected:true,undoRedoAndReload:true,collisionRejected:true,ok:true,browserVersion:browser.version(),sourceSha256:sha(source),downloadedSha256:sha(downloaded),downloads,initialReads:reads,metadataAndContentRetry:true,cacheAndExclusiveSidebar:true,staleDownloadsRejected:true,actualPreviewAndReadonlyDownloads:true,emptyAndDuplicateNames:true,operations:savedOperations,provenance:'production static UI; actual PDF.js/packed engine; Worker failures; substituted auth/revision routes, no production claim'}
  evidence.keyboardChecked=process.env.PDF_ATTACHMENTS_KEYBOARD==='1';evidence.sidebarLayouts=sidebarLayouts;Object.assign(evidence,await verifyAssets())
  const dir=process.env.PDF_ATTACHMENTS_EVIDENCE_DIR
  if(dir){await mkdir(dir,{recursive:true});await writeFile(`${dir}/source.pdf`,source);await writeFile(`${dir}/downloaded.pdf`,downloaded);await writeFile(`${dir}/evidence.json`,JSON.stringify(evidence,null,2));await page.screenshot({path:`${dir}/mobile.png`,fullPage:true})}
  console.log(JSON.stringify(evidence))
} catch(error) { console.error(await page?.locator('body').innerText()); throw error } finally {await browser?.close();server.kill('SIGTERM')}
