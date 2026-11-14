import assert from 'node:assert/strict'
import {spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import {chromium} from 'playwright'
import {createServer,preview} from 'vite'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=resolve(frontend,'../../..'),directory=resolve(process.env.PDF_COMPARE_OUTPUT??'/dev/shm/office-pdf-compare-source-20261113/browser')
await mkdir(directory,{recursive:true})
const hash=bytes=>createHash('sha256').update(bytes).digest('hex'),requests=[],errors=[],results=[],assets=new Map(),assetChecks=[],assetErrors=[]
const staticRoot=process.env.PDF_COMPARE_STATIC_ROOT?resolve(process.env.PDF_COMPARE_STATIC_ROOT):null,sourceRoot=process.env.PDF_COMPARE_SOURCE_ROOT?resolve(process.env.PDF_COMPARE_SOURCE_ROOT):frontend,pdfDirectory=process.env.PDF_COMPARE_SOURCE_PDF_DIRECTORY?resolve(process.env.PDF_COMPARE_SOURCE_PDF_DIRECTORY):null
const sourceHashes={}
for(const name of ['src/pdf-main.ts','src/pdf-view-ribbon.ts','src/pdf-compare.tsx','src/pdf-compare-compute.ts','src/pdf-compare-worker.ts','src/pdf-compare.css','src/vendor/genoffice-pdf/renderer/ComparePanel.tsx','src/vendor/genoffice-pdf/renderer/compare-text.ts'])sourceHashes[name]=hash(await readFile(resolve(sourceRoot,name)))
let manifestSha256=null,sources
if(staticRoot){assert.ok(pdfDirectory&&process.env.PDF_COMPARE_SOURCE_ROOT&&process.env.PDF_COMPARE_MANIFEST_SHA256);manifestSha256=hash(await readFile(resolve(staticRoot,'.vite/manifest.json')));assert.equal(manifestSha256,process.env.PDF_COMPARE_MANIFEST_SHA256)}
if(pdfDirectory){
 const previous=JSON.parse(await readFile(resolve(pdfDirectory,'evidence.json'),'utf8'));sources={}
 for(const[name,identity]of Object.entries(previous.sources)){const bytes=await readFile(resolve(pdfDirectory,`${name}.pdf`));assert.equal(hash(bytes),identity.sha256);assert.equal(bytes.length,identity.size);sources[name]={...identity,bytes}}
 const inspected=spawnSync(resolve(repo,'.venv/bin/python'),['-c','import json,sys;from pathlib import Path;from smart_reporting.reporting.delivery.pdf_native import inspect_pdf;print(json.dumps(inspect_pdf(Path(sys.argv[1]).read_bytes())))',resolve(pdfDirectory,'original.pdf')],{cwd:repo,env:{...process.env,PYTHONPATH:repo},encoding:'utf8'});assert.equal(inspected.status,0,inspected.stderr);sources.original.model=JSON.parse(inspected.stdout)
}else{
 const generated=spawnSync(resolve(repo,'.venv/bin/python'),[resolve(frontend,'smoke/pdf-compare-source.py')],{cwd:repo,env:{...process.env,PYTHONPATH:repo},encoding:'utf8',maxBuffer:20*1024*1024});assert.equal(generated.status,0,generated.stderr);sources=JSON.parse(generated.stdout)
 for(const value of Object.values(sources)){value.bytes=Buffer.from(value.bytes,'base64');value.sha256=hash(value.bytes);value.size=value.bytes.length}
}
for(const[name,value]of Object.entries(sources))await writeFile(resolve(directory,`${name}.pdf`),value.bytes)
const port=Number(process.env.PDF_COMPARE_PORT??4466)
const server=staticRoot?await preview({root:frontend,configFile:resolve(frontend,'vite.config.ts'),build:{outDir:staticRoot},preview:{host:'127.0.0.1',port,strictPort:true}}):await createServer({root:frontend,configFile:resolve(frontend,'vite.config.ts'),cacheDir:resolve(directory,'vite-cache'),server:{host:'127.0.0.1',port,strictPort:true,watch:{ignored:['**/*']}}})
if(!staticRoot)await server.listen()
const base=new URL(server.resolvedUrls.local[0]).origin
let browser
try{
 browser=await chromium.launch({headless:true})
 const viewports=process.env.PDF_COMPARE_VIEWPORTS?.split(',').map(value=>value.split('x').map(Number))??[[1440,900],[390,844],[1024,480]]
 for(const[width,height]of viewports){
  const key=`${width}x${height}`,page=await browser.newPage({viewport:{width,height}}),path=`/reports/v1/native/pdf-compare-${key}/1`,source=sources.original
  page.on('pageerror',error=>errors.push({key,message:error.message}))
  if(staticRoot)await page.route('**/reports/v1/editor/assets/**',async route=>{
   const url=new URL(route.request().url()),prefix='/reports/v1/editor/assets/'
   if(!/\.(?:m?js|css)$/.test(url.pathname))return route.continue()
   const check=(async()=>{const path=decodeURIComponent(url.pathname.slice(prefix.length));assert.ok(!path.split('/').includes('..'));const response=await route.fetch();assert.equal(response.status(),200);const bytes=await response.body(),sha256=hash(bytes);assert.equal(sha256,hash(await readFile(resolve(staticRoot,path))),path);assets.set(path,{path,size:bytes.length,sha256});await route.fulfill({response,body:bytes})})()
   assetChecks.push(check.catch(error=>assetErrors.push(String(error))))
   await check.catch(async()=>{await route.abort().catch(()=>{})})
  })
  await page.addInitScript(()=>{
   if(location.origin!=='null')localStorage.clear()
   const NativeWorker=window.Worker,state={hold:false,deferred:[],created:0,terminated:0,urls:[]};window.__pdfCompareWorkerEvidence=state
   window.Worker=class extends NativeWorker{
    constructor(url,options){super(url,options);this.isCompare=String(url).includes('pdf-compare-worker');if(this.isCompare){state.created++;state.urls.push(String(url))}}
    set onmessage(handler){super.onmessage=event=>{if(this.isCompare&&state.hold)state.deferred.push(()=>handler?.call(this,event));else handler?.call(this,event)}}
    terminate(){if(this.isCompare)state.terminated++;super.terminate()}
   }
  })
  await page.route(`**${path}/api/**`,async route=>{
   const operation=new URL(route.request().url()).pathname.split('/').at(-1);requests.push({key,operation,method:route.request().method()})
   if(operation==='context')return route.fulfill({json:{context:{documentId:`pdf-compare-${key}`,revision:1,parentRevision:null,format:'pdf',origin:'upload',scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},sourceFile:{path:'original.pdf',size:source.size,sha256:source.sha256,mediaType:'application/pdf'}},csrfToken:'fixture',capabilities:{pdf_editor:true},editingEnabled:true}})
   if(operation==='file')return route.fulfill({body:source.bytes,contentType:'application/pdf'})
   if(operation==='preview'){assert.deepEqual(route.request().postDataJSON().operations,[]);return route.fulfill({json:{sourceSha256:source.sha256,model:source.model,appliedOperationIndices:[],skippedOperations:[]}})}
   return route.fulfill({status:500,json:{detail:{code:'fixture_read_only',message:'比较验证不保存或发布'}}})
  })
  await page.route(`**${path}`,async route=>route.fulfill({response:await route.fetch({url:`${base}/reports/v1/editor/assets/native.html`})}))
  await page.goto(new URL(path,base).href)
  await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false'&&document.querySelector('.pdf-page-content canvas'),null,{timeout:60000}).catch(async error=>{await writeFile(resolve(directory,`load-failure-${key}.txt`),await page.locator('body').innerText());await page.screenshot({path:resolve(directory,`load-failure-${key}.png`)});throw error})
  const draft=()=>page.evaluate(()=>Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).map(([key,value])=>[key,JSON.parse(value).operations]))
  const before=await draft()
  await page.locator('[data-pdf-ribbon-tab="view"]').click()
  const entry=page.locator('[data-source-command-id="genoffice.pdf.view.navigation.compare"]');assert.equal(await entry.isEnabled(),true);await entry.click()
  const panel=page.locator('.pdf-compare-sidebar'),pick=panel.locator('.pdf-compare-pick')
  assert.equal(await pick.evaluate(node=>node===document.activeElement),true)
  const choose=async name=>{await pick.scrollIntoViewIfNeeded();const[chooser]=await Promise.all([page.waitForEvent('filechooser'),pick.click()]);await chooser.setFiles(resolve(directory,`${name}.pdf`));await page.waitForFunction(()=>document.querySelector('.pdf-compare-sidebar [aria-busy]')?.getAttribute('aria-busy')==='false')}
  const disposeComparison=async()=>{
   await page.evaluate(()=>{window.__pdfCompareWorkerEvidence.hold=true})
   const terminatedBefore=await page.evaluate(()=>window.__pdfCompareWorkerEvidence.terminated)
   await panel.locator('.pdf-compare-swap').click();await page.waitForFunction(()=>window.__pdfCompareWorkerEvidence.deferred.length>0)
   await page.evaluate(()=>window.dispatchEvent(new Event('pagehide')))
   const disposal=await page.evaluate(()=>{const state=window.__pdfCompareWorkerEvidence;state.deferred.splice(0).forEach(deliver=>deliver());return{created:state.created,terminated:state.terminated,urls:state.urls,editorChildren:document.querySelector('#report-editor')?.childElementCount}})
   assert.ok(disposal.terminated>terminatedBefore);assert.equal(disposal.editorChildren,0)
   return{...disposal,responseDeferredByFixture:true,terminatedOnDispose:true,lateResultIgnored:true}
  }
  await choose('changed');await panel.locator('.pdf-modal-hint').filter({hasText:'有 3 页存在文本差异'}).waitFor()
  const identity=await panel.locator('[data-pdf-compare-identity]').evaluate(node=>({sha256:node.dataset.sha256,size:Number(node.dataset.size)}));assert.deepEqual(identity,{sha256:sources.changed.sha256,size:sources.changed.size})
  if(process.env.PDF_COMPARE_ONLY==='dispose'){
   await page.screenshot({path:resolve(directory,`dispose-before-${key}.png`)});assert.deepEqual(await draft(),before)
   results.push({key,identity,disposal:await disposeComparison(),draftUnchanged:true})
   await Promise.all(assetChecks);await page.goto('about:blank');await page.close();continue
  }
  const extra=panel.locator('.pdf-compare-row[data-page-index="3"]');assert.equal(await extra.isDisabled(),true);assert.match(await extra.textContent(),/\+1 行/)
  await panel.locator('.pdf-compare-swap').click();await page.waitForFunction(()=>document.querySelector('.pdf-compare-sidebar [aria-busy]')?.getAttribute('aria-busy')==='false');assert.match(await extra.textContent(),/−1 行/);await panel.locator('.pdf-compare-swap').click();await page.waitForFunction(()=>document.querySelector('.pdf-compare-sidebar [aria-busy]')?.getAttribute('aria-busy')==='false')
  const jumps=[]
  for(const index of [1,2]){
   const row=panel.locator(`.pdf-compare-row[data-page-index="${index}"]`),id=`sha256:${source.sha256}:page:${index}`
   await row.scrollIntoViewIfNeeded();await row.click()
   await page.waitForFunction(id=>{const card=[...document.querySelectorAll('.pdf-page')].find(node=>node.dataset.pageId===id),viewport=document.querySelector('.pdf-document-pages');return card?.classList.contains('is-active')&&viewport&&Math.abs(card.getBoundingClientRect().top-viewport.getBoundingClientRect().top)<20},id)
   await page.locator(`.pdf-page[data-page-id="${id}"] canvas`).waitFor();jumps.push({index,id,actualScroll:true,canvas:true})
  }
  await page.screenshot({path:resolve(directory,`differences-${key}.png`)})
  await panel.getByRole('button',{name:'关闭文档比较'}).click();assert.equal(await panel.isVisible(),false)
  assert.equal(await entry.evaluate(node=>node===document.activeElement||document.activeElement?.matches('[data-pdf-ribbon-tab][aria-selected="true"]')),true)
  await entry.click();await choose('original');await panel.locator('.pdf-modal-hint').filter({hasText:'两个文档的文本一致'}).waitFor();assert.equal(await panel.locator('.pdf-compare-row').count(),0)
  await choose('original');await panel.locator('.pdf-modal-hint').filter({hasText:'两个文档的文本一致'}).waitFor()
  await panel.locator('input[type=file]').dispatchEvent('cancel');assert.match(await panel.textContent(),/取消文件选择/);assert.match(await panel.textContent(),/两个文档的文本一致/)
  await choose('scan');assert.match(await panel.textContent(),/无可提取文本/);assert.match(await panel.textContent(),/无法判断视觉内容/)
  await choose('password');assert.match(await panel.textContent(),/需要密码/);assert.equal(await panel.locator('.pdf-compare-row').count(),0)
  await choose('invalid');assert.match(await panel.textContent(),/比较失败/)
  await choose('changed');await panel.locator('.pdf-modal-hint').filter({hasText:'有 3 页存在文本差异'}).waitFor()
  if(width===1440){
   const[chooser]=await Promise.all([page.waitForEvent('filechooser'),pick.click()]);await chooser.setFiles(resolve(directory,'slow.pdf'))
   await panel.getByRole('button',{name:'取消比较',exact:true}).click()
   assert.match(await panel.textContent(),/已取消本次比较/)
   assert.equal(await panel.locator('[aria-busy]').getAttribute('aria-busy'),'false')
   await page.waitForTimeout(100);assert.match(await panel.textContent(),/有 3 页存在文本差异/)
  }
  await page.screenshot({path:resolve(directory,`complete-${key}.png`)})
  assert.deepEqual(await draft(),before)
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2);assert.equal(overflow,false)
  results.push({key,identity,jumps,swapped:true,extraDisabled:true,identical:true,repeatedFile:true,cancelRetains:true,scanHonest:true,passwordFailure:true,invalidFailure:true,activeCancellation:width===1440,focusReturn:true,draftUnchanged:true,horizontalOverflow:false,disposal:await disposeComparison()})
  await Promise.all(assetChecks)
  await page.goto('about:blank');await page.close()
 }
 assert.deepEqual(errors,[]);assert.ok(requests.every(request=>['context','file','preview'].includes(request.operation)))
 for(const[name,value]of Object.entries(sources))assert.equal(hash(await readFile(resolve(directory,`${name}.pdf`))),value.sha256)
 await Promise.all(assetChecks);assert.deepEqual(assetErrors,[])
 if(staticRoot){assert.equal(hash(await readFile(resolve(staticRoot,'.vite/manifest.json'))),manifestSha256);assert.ok([...assets.keys()].some(path=>path.includes('pdf-compare-worker')),'actual comparison Worker HTTP resource must be hash checked');assert.ok([...assets.keys()].some(path=>path.endsWith('.css')))}
 await writeFile(resolve(directory,'evidence.json'),JSON.stringify({scope:`Real ${staticRoot?'frozen':'development'} native host, pinned comparison UI/LCS, PDF.js and user-triggered browser file chooser. Context/file/initial preview are HTTP fixtures. For dispose only, a native Worker subclass defers delivery of a real computed response until pagehide, records terminate, then replays that late response; no algorithm or worker execution is simulated. No save/export/publication.`,build:{staticRoot,sourceRoot,sourceHashes,manifestSha256},sources:Object.fromEntries(Object.entries(sources).map(([name,value])=>[name,{sha256:value.sha256,size:value.size}])),results,errors,requests,assets:[...assets.values()],assetResponseChecks:assetChecks.length,assetErrors},null,2))
 console.log(JSON.stringify({results,errors,requests},null,2))
}catch(error){await writeFile(resolve(directory,'failure.json'),JSON.stringify({error:String(error),stack:error.stack,build:{staticRoot,sourceRoot,sourceHashes,manifestSha256},results,errors,requests,assets:[...assets.values()],assetResponseChecks:assetChecks.length,assetErrors},null,2));throw error}
finally{await browser?.close();if(staticRoot)await new Promise(resolve=>server.httpServer.close(resolve));else await server.close()}
