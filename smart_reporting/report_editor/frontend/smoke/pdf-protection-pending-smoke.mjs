import assert from 'node:assert/strict'
import {spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import {chromium} from 'playwright'
import {createServer,preview} from 'vite'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=resolve(frontend,'../../..')
const directory=resolve(process.env.PDF_PROTECTION_PENDING_OUTPUT??'/dev/shm/office-current-state-pdf-20261113/red')
await mkdir(directory,{recursive:true})
const hash=bytes=>createHash('sha256').update(bytes).digest('hex')
const staticRoot=process.env.PDF_PROTECTION_PENDING_STATIC_ROOT?resolve(process.env.PDF_PROTECTION_PENDING_STATIC_ROOT):null
const sourceRoot=process.env.PDF_PROTECTION_PENDING_SOURCE_ROOT?resolve(process.env.PDF_PROTECTION_PENDING_SOURCE_ROOT):frontend
const sourceHashes={}
for(const file of ['src/pdf-protection.ts','src/pdf-main.ts','src/pdf.css'])sourceHashes[file]=hash(await readFile(resolve(sourceRoot,file)))
let manifestSha256=null
if(staticRoot){
 assert.ok(process.env.PDF_PROTECTION_PENDING_MANIFEST_SHA256&&process.env.PDF_PROTECTION_PENDING_SOURCE_ROOT,'冻结模式显式指定manifest SHA和源码快照目录')
 manifestSha256=hash(await readFile(resolve(staticRoot,'.vite/manifest.json')))
 assert.equal(manifestSha256,process.env.PDF_PROTECTION_PENDING_MANIFEST_SHA256)
}
const sourcePdf=process.env.PDF_PROTECTION_PENDING_SOURCE_PDF?resolve(process.env.PDF_PROTECTION_PENDING_SOURCE_PDF):null
const generated=spawnSync(resolve(repo,'.venv/bin/python'),['-c',`
import base64,io,json,sys
from pathlib import Path
from pypdf import PdfWriter
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf
if len(sys.argv)>1:data=Path(sys.argv[1]).read_bytes()
else:
 writer=PdfWriter()
 for size in [(612,792),(500,400),(320,480)]:writer.add_blank_page(*size)
 writer.add_metadata({'/Title':'Protection current-state fixture'})
 output=io.BytesIO();writer.write(output);data=output.getvalue()
print(json.dumps({'bytes':base64.b64encode(data).decode(),'model':inspect_pdf(data)}))
`,...(sourcePdf?[sourcePdf]:[])],{cwd:repo,encoding:'utf8',maxBuffer:10*1024*1024})
assert.equal(generated.status,0,generated.stderr)
const source=JSON.parse(generated.stdout),bytes=Buffer.from(source.bytes,'base64')
assert.equal(source.model.capabilities.protectPdf,true)
await writeFile(resolve(directory,'source.pdf'),bytes)
const port=Number(process.env.PDF_PROTECTION_PENDING_PORT??4463)
const server=staticRoot
 ?await preview({root:frontend,configFile:resolve(frontend,'vite.config.ts'),build:{outDir:staticRoot},preview:{host:'127.0.0.1',port,strictPort:true}})
 :await createServer({root:frontend,configFile:resolve(frontend,'vite.config.ts'),cacheDir:resolve(directory,'vite-cache'),server:{host:'127.0.0.1',port,strictPort:true}})
if(!staticRoot)await server.listen()
const base=new URL(server.resolvedUrls.local[0]).origin,path='/reports/v1/native/pdf-protection-pending/1'
const requests=[],errors=[],results=[],failures=[],assets=new Map(),assetChecks=[],assetErrors=[]
let pending,browser
const artifact={documentId:'protection-fixture',revision:1,parentRevision:null,revisionRegistered:false,artifacts:{pdf:{downloadUrl:'/fixture/protection.pdf'}},validation:{ok:false,issues:[{code:'fixture-review',message:'夹具：请核对实际文件'}]}}
const modes=process.env.PDF_PROTECTION_PENDING_MODES?.split(',')??['success','failure','close-click','close-Escape']
try{
 browser=await chromium.launch({headless:true})
 const page=await browser.newPage()
 page.on('pageerror',error=>errors.push(error.message))
 // HTTP 503 below is an intentional error fixture, not a console regression.
 page.on('console',entry=>{if(entry.type()==='error'&&!entry.text().includes('503'))errors.push(entry.text())})
 if(staticRoot)page.on('response',response=>{
  const url=new URL(response.url()),prefix='/reports/v1/editor/assets/'
  if(!url.pathname.startsWith(prefix)||!/\.(?:m?js|css)$/.test(url.pathname))return
  assetChecks.push((async()=>{
   const path=decodeURIComponent(url.pathname.slice(prefix.length))
   assert.ok(!path.split('/').includes('..'));assert.equal(response.status(),200)
   const bytes=await response.body(),sha256=hash(bytes)
   assert.equal(sha256,hash(await readFile(resolve(staticRoot,path))),path)
   assets.set(path,{path,size:bytes.length,sha256})
  })().catch(error=>assetErrors.push(String(error))))
 })
 await page.addInitScript(()=>localStorage.clear())
 await page.route(`**${path}/api/**`,async route=>{
  const operation=new URL(route.request().url()).pathname.split('/').at(-1)
  requests.push({operation,method:route.request().method()})
  if(operation==='context')return route.fulfill({json:{context:{documentId:'pdf-protection-pending',revision:1,parentRevision:null,format:'pdf',origin:'upload',scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},sourceFile:{path:'source.pdf',size:bytes.length,sha256:source.model.sourceSha256,mediaType:'application/pdf'}},csrfToken:'fixture',capabilities:{pdf_editor:true},editingEnabled:true}})
  if(operation==='file')return route.fulfill({body:bytes,contentType:'application/pdf'})
  if(operation==='preview'){assert.deepEqual(route.request().postDataJSON().operations,[]);return route.fulfill({json:{sourceSha256:source.model.sourceSha256,model:source.model,appliedOperationIndices:[],skippedOperations:[]}})}
  if(operation==='protect-pdf'){
   assert.equal(pending,undefined)
   const payload=route.request().postDataJSON()
   assert.equal(payload.expectedSha256,source.model.sourceSha256)
   assert.equal(payload.userPassword,'reader-secret');assert.equal(payload.ownerPassword,'owner-secret')
   await new Promise(resolve=>{pending={permissions:payload.permissions,release:async fail=>{await route.fulfill(fail?{status:503,json:{detail:{code:'fixture_protection_failed',message:'夹具：保护副本生成失败，请重试'}}}:{json:artifact});pending=undefined;resolve()}}})
   return
  }
  return route.fulfill({status:500,json:{detail:'本批不执行保存或发布'}})
 })
 await page.route(`**${path}`,async route=>route.fulfill({response:await route.fetch({url:`${base}/reports/v1/editor/assets/native.html`})}))
 await page.goto(new URL(path,base).href)
 await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false'&&document.querySelector('.pdf-page-content canvas'),null,{timeout:60000})
 const operations=()=>page.evaluate(()=>Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).map(([key,value])=>[key,JSON.parse(value).operations]))
 const original=await operations(),entry=page.locator('[data-source-command-id="genoffice.pdf.annotate.protection.protect"]'),dialog=page.getByRole('dialog',{name:'保护 PDF',exact:true})
 const passwords=dialog.locator('input[type=password]'),copy=dialog.getByRole('checkbox',{name:'允许复制',exact:true}),apply=dialog.getByRole('button',{name:'生成保护 PDF',exact:true}),close=dialog.getByRole('button',{name:'关闭',exact:true})
 for(const [width,height]of [[1440,900],[390,844],[640,360]])for(const mode of modes){
  const key=`${mode}-${width}x${height}`
  await page.setViewportSize({width,height});await page.locator('[data-pdf-ribbon-tab="annotate"]').click();await entry.click();await dialog.waitFor()
  // Existing local validation retains values and does not send a request.
  await passwords.nth(0).fill('reader-secret');await passwords.nth(1).fill('mismatch');const count=requests.length
  await apply.click();await dialog.getByRole('status').filter({hasText:'两次输入必须一致'}).waitFor()
  assert.equal(await passwords.nth(0).inputValue(),'reader-secret');assert.equal(await passwords.nth(1).inputValue(),'mismatch');assert.equal(requests.length,count)
  await passwords.nth(1).fill('reader-secret');await passwords.nth(2).fill('owner-secret');await copy.uncheck()
  await apply.click();await page.waitForFunction(()=>document.querySelector('dialog[open] [data-pdf-protection-apply]')?.disabled)
  while(!pending)await new Promise(resolve=>setTimeout(resolve,10))
  const submitted={...pending.permissions}
  const locked=await dialog.locator('input').evaluateAll(nodes=>nodes.every(node=>node.disabled))
  assert.ok(await apply.isDisabled());assert.deepEqual(await passwords.evaluateAll(nodes=>nodes.map(node=>node.value)),['','',''])
  await copy.scrollIntoViewIfNeeded();const rect=await copy.boundingBox();assert.ok(rect)
  const hit=await copy.evaluate(node=>{const r=node.getBoundingClientRect();return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===node})
  await page.mouse.click(rect.x+rect.width/2,rect.y+rect.height/2)
  const busyCopy=await copy.isChecked()
  await page.screenshot({path:resolve(directory,`${key}-pending.png`)})
  if(mode.startsWith('close-')){
   await close.scrollIntoViewIfNeeded()
   if(mode==='close-click')await close.click();else await page.keyboard.press('Escape')
   await dialog.waitFor({state:'hidden'})
   const focusReturned=await entry.evaluate(node=>document.activeElement===node)
   assert.ok(focusReturned)
   await pending.release(false);await page.waitForTimeout(50);await entry.click();await dialog.waitFor()
  }else await pending.release(mode==='failure')
  await page.waitForFunction(()=>!document.querySelector('dialog[open] [data-pdf-protection-apply]')?.disabled)
  const enabled=await dialog.locator('input').evaluateAll(nodes=>nodes.every(node=>!node.disabled))
  assert.ok(enabled);assert.deepEqual(await passwords.evaluateAll(nodes=>nodes.map(node=>node.value)),['','',''])
  if(mode==='failure')await dialog.getByRole('status').filter({hasText:'保护副本生成失败'}).waitFor()
  else {await dialog.getByRole('link',{name:'下载保护 PDF'}).waitFor();assert.ok((await dialog.getByRole('status').textContent()).includes('验收未通过'))}
  const displayedCopy=await copy.isChecked(),consistent=displayedCopy===submitted.copying
  assert.deepEqual(await operations(),original)
  await close.scrollIntoViewIfNeeded();const closeHit=await close.evaluate(node=>{const r=node.getBoundingClientRect();return node.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))})
  await page.screenshot({path:resolve(directory,`${key}-settled.png`)})
  await close.click();await dialog.waitFor({state:'hidden'});assert.ok(await entry.evaluate(node=>document.activeElement===node))
  results.push({key,locked,hit,submitted,busyCopy,displayedCopy,consistent,enabled,closeHit,credentialsCleared:true,localErrorRetained:true,draftUnchanged:true,focusReturned:true})
  if(!locked||busyCopy!==submitted.copying||!consistent||!closeHit)failures.push({key,locked,submitted,busyCopy,displayedCopy,consistent,closeHit})
 }
 assert.deepEqual(errors,[])
 assert.ok(requests.every(request=>['context','file','preview','protect-pdf'].includes(request.operation)))
 await Promise.all(assetChecks);assert.deepEqual(assetErrors,[])
 if(staticRoot){
  assert.equal(hash(await readFile(resolve(staticRoot,'.vite/manifest.json'))),manifestSha256)
  const manifest=JSON.parse(await readFile(resolve(staticRoot,'.vite/manifest.json'),'utf8'))
  const pdf=Object.values(manifest).find(entry=>entry.name==='pdf-main'&&entry.isDynamicEntry)
  assert.ok(pdf&&assets.has(pdf.file),'实际PDF模块必须来自所指定冻结构建')
  assert.ok([...assets.keys()].some(path=>path.endsWith('.css')))
 }
 const build={staticRoot,manifestSha256,sourceRoot,sourceHashes}
 await writeFile(resolve(directory,'evidence.json'),JSON.stringify({scope:`Actual ${staticRoot?'frozen':'development'} native host and PDF.js; context/file/initial preview and delayed protection responses are explicit HTTP fixtures. No real protection artifact, download, save, export or publication.`,build,sourceHashes,source:{input:sourcePdf,sha256:hash(bytes),size:bytes.length,pages:source.model.pages.length},results,failures,requests,assets:[...assets.values()],assetErrors,errors},null,2))
 console.log(JSON.stringify({cases:results.length,failures,requests,errors},null,2));assert.deepEqual(failures,[],'Pending protection inputs must retain the submitted state')
}catch(error){await writeFile(resolve(directory,'failure.json'),JSON.stringify({error:String(error),stack:error.stack,build:{staticRoot,manifestSha256,sourceRoot,sourceHashes},results,failures,requests,assets:[...assets.values()],assetErrors,errors},null,2));throw error}
finally{if(pending)await pending.release(true);await browser?.close();if(staticRoot)await new Promise(resolve=>server.httpServer.close(resolve));else await server.close()}
