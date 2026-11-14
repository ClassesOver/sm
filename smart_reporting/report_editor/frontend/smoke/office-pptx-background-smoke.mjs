import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {readFile,writeFile,mkdir,readdir} from 'node:fs/promises'
import {createServer} from 'node:http'
import {spawnSync} from 'node:child_process'
import {resolve,extname} from 'node:path'
import {fileURLToPath} from 'node:url'
import {chromium} from 'playwright'
import {inspectBackgroundLayout} from './office-pptx-background-layout.mjs'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=resolve(frontend,'../../..')
const directory=process.env.PPTX_BACKGROUND_DIRECTORY,staticRoot=process.env.PPTX_BACKGROUND_STATIC
assert.ok(directory&&staticRoot,'显式指定构建和证据目录');await mkdir(directory,{recursive:true})
const baseline=process.env.PPTX_BACKGROUND_BASELINE==='1',reviewOnly=process.env.PPTX_BACKGROUND_REVIEW_ONLY==='1'
assert.ok(!baseline||!reviewOnly)
const entries=await readdir(directory)
if(!reviewOnly)assert.equal(entries.some(n=>/^(?:saved|revision-2|downloaded)/.test(n)),false,'禁止重放已成功保存的来源')
const sha=b=>createHash('sha256').update(b).digest('hex'),manifest=sha(await readFile(resolve(staticRoot,'.vite/manifest.json')))
assert.equal(manifest,process.env.PPTX_BACKGROUND_EXPECTED_MANIFEST_SHA256)
const scripts=['office-pptx-background-smoke.mjs','office-pptx-background-fixture.py','office-pptx-background-layout.mjs'],hashes={}
for(const name of scripts)hashes[name]=sha(await readFile(resolve(frontend,'smoke',name)))
const bridgeHashes={};for(const name of ['edit-pptx.mjs','render-pptx.mjs'])bridgeHashes[name]=sha(await readFile(resolve(repo,'smart_reporting/reporting/slides_engine/dist',name)))
const engine=p=>{const r=spawnSync(resolve(repo,'.venv/bin/python'),[resolve(frontend,'smoke/office-pptx-background-fixture.py')],{cwd:repo,env:{...process.env,PYTHONPATH:repo,TMPDIR:'/dev/shm',PYTHONDONTWRITEBYTECODE:'1'},input:JSON.stringify({directory,...p}),encoding:'utf8',maxBuffer:20*1024*1024,timeout:120000});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout)}
const file=n=>resolve(directory,`revision-${n}.pptx`),revisions={1:engine(entries.includes('revision-1.pptx')?{mode:'inspect',source:file(1)}:{mode:'create'})}
let saved,saveCount=0,saveAttempted=false,browser,page,stage='setup',routeError
if(reviewOnly){saved=JSON.parse(await readFile(resolve(directory,'saved.json'),'utf8'));revisions[2]=engine({mode:'inspect',source:file(2)});assert.equal(revisions[2].sha256,saved.sha256)}
const docId='background-pc',prefix='/reports/v1/editor/assets/',layout={cases:[],failures:[]},errors=[],checks=[],resources=new Map(),steps=[]
const server=createServer(async(req,res)=>{try{
 const path=new URL(req.url,'http://localhost').pathname
 if(path==='/favicon.ico'){res.writeHead(204);res.end();return}
 if(path==='/download/2.pptx'){assert.ok(saved);const bytes=await readFile(file(2));res.writeHead(200,{'Content-Type':'application/vnd.openxmlformats-officedocument.presentationml.presentation','Content-Disposition':'attachment; filename=background.pptx','Content-Length':bytes.length});res.end(bytes);return}
 assert.ok(path.startsWith(prefix));const target=resolve(staticRoot,path.slice(prefix.length));assert.ok(target.startsWith(staticRoot+'/'));const bytes=await readFile(target)
 res.writeHead(200,{'Content-Type':{'.js':'application/javascript','.css':'text/css','.html':'text/html','.woff2':'font/woff2','.wasm':'application/wasm'}[extname(target)]??'application/octet-stream'});res.end(bytes)
 }catch{res.writeHead(404);res.end('not found')}})
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const base=`http://127.0.0.1:${server.address().port}`,pathBase=`/reports/v1/native/${docId}/`
try{
 browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1440,height:900},acceptDownloads:true})
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});page.on('dialog',d=>d.type()==='beforeunload'?d.accept():d.dismiss())
 page.on('response',r=>{const path=new URL(r.url()).pathname;if(r.status()>=400)errors.push(`${r.status()} ${path}`);if(r.status()===200&&path.startsWith(prefix)&&/\.(?:js|css)$/.test(path))checks.push(r.body().then(async bytes=>{assert.equal(sha(bytes),sha(await readFile(resolve(staticRoot,path.slice(prefix.length)))));resources.set(path,{sha256:sha(bytes),size:bytes.length})}).catch(e=>errors.push(String(e))))})
 await page.route(new RegExp(pathBase+'[0-9]+$'),async route=>route.fulfill({body:await readFile(resolve(staticRoot,'native.html')),contentType:'text/html'}))
 await page.route('**'+pathBase+'*/api/**',async route=>{try{
  const request=route.request(),path=new URL(request.url()).pathname,n=Number(path.split('/')[5]),entry=revisions[n],post=request.method()==='POST'?request.postDataJSON():undefined
  if(path.endsWith('/context'))return route.fulfill({json:{context:{documentId:docId,format:'pptx',revision:n,parentRevision:n-1,scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},sourceFile:{path:`revision-${n}.pptx`,size:entry.size,sha256:entry.sha256,mediaType:'application/vnd.openxmlformats-officedocument.presentationml.presentation'},origin:'upload'},csrfToken:'fixture',capabilities:{pptx_editor:true},editingEnabled:true}})
  if(path.endsWith('/file'))return route.fulfill({body:await readFile(file(n)),contentType:'application/vnd.openxmlformats-officedocument.presentationml.presentation'})
  if(path.endsWith('/preview.pdf')&&request.method()==='GET')return route.fulfill({status:204,body:''})
  assert.equal(post?.expectedSha256,entry.sha256)
  if(path.endsWith('/preview')){const preview=engine({mode:'inspect',source:file(n),operations:post.operations});return route.fulfill({json:{sourceSha256:entry.sha256,draftSha256:preview.sha256,model:preview.model}})}
  if(path.endsWith('/render-tree'))return route.fulfill({json:engine({mode:'render',source:file(n),operations:post.operations})})
  assert.ok(path.endsWith('/save'));assert.equal(reviewOnly,false,'只读模式禁止保存');assert.equal(baseline,false);assert.equal(saveAttempted,false,'只能保存一次');assert.equal(n,1);saveAttempted=true
  revisions[2]=engine({mode:'patch',source:file(1),output:file(2),operations:post.operations});saved={...revisions[2],operations:post.operations};delete saved.model
  saveCount++;await writeFile(resolve(directory,'saved.json'),JSON.stringify(saved,null,2))
  return route.fulfill({json:{documentId:docId,revision:2,parentRevision:1,revisionRegistered:true,artifacts:{pptx:{downloadUrl:base+'/download/2.pptx',size:saved.size,sha256:saved.sha256}},editor:{openUrl:pathBase+'2'},validation:{ok:false,issues:[{code:'manual_review',message:'背景版式待复核，文件已生成。'}]}}})
 }catch(e){routeError=String(e);await route.fulfill({status:500,json:{detail:routeError}})}})
 const open=async n=>{await page.goto(base+pathBase+n);await page.locator('.slides-canvas canvas').first().waitFor({timeout:60000})}
 const draft=()=>page.evaluate(()=>Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).flatMap(([,value])=>JSON.parse(value).operations))
 const waitDraft=expected=>page.waitForFunction(expected=>JSON.stringify(Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).flatMap(([,value])=>JSON.parse(value).operations))===JSON.stringify(expected),expected)
 const dialog=page.getByRole('dialog',{name:'设置背景格式',exact:true}),opener=mode=>page.locator(`[data-command="${mode==='image'?'backgroundImage':'formatBackground'}"]`)
 const openDialog=async mode=>{await page.locator('[data-ribbon-tab=design]').click();await opener(mode).click();await dialog.waitFor()}
 const inspect=phase=>inspectBackgroundLayout(page,{directory,phase,layout,draft})
 const selectSlide=async index=>page.locator('.slide-row').nth(index).locator('.slide-open').click()
 const choose=async path=>{const waiting=page.waitForEvent('filechooser');await dialog.locator('button[value=ok]').click();await(await waiting).setFiles(path)}
 const history=async(label,before)=>{
  await page.waitForFunction(before=>JSON.stringify(Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).flatMap(([,value])=>JSON.parse(value).operations))!==JSON.stringify(before),before)
  const after=await draft();await page.locator('[data-source-action=onUndo]').click();await waitDraft(before);await page.locator('[data-source-action=onRedo]').click();await waitDraft(after)
  steps.push({label,before,after,undoRedo:true});await writeFile(resolve(directory,'steps.json'),JSON.stringify(steps,null,2));return after
 }
 await open(reviewOnly?2:1)
 if(process.env.PPTX_BACKGROUND_DIAGNOSTIC==='1'){
  assert.equal(baseline,true);await openDialog('image')
  const diagnostic=await dialog.getByRole('button',{name:'关闭设置背景格式',exact:true}).evaluate(n=>{
   const inspect=()=>{const r=n.getBoundingClientRect(),s=getComputedStyle(n),hits=points=>points.map(([x,y])=>{const hit=document.elementFromPoint(x,y);return {x,y,hit:hit?.tagName,label:hit?.getAttribute('aria-label'),inside:n.contains(hit)}});return {width:r.width,height:r.height,radius:s.borderRadius,zIndex:s.zIndex,corners:hits([[r.x+r.width/2,r.y+r.height/2],[r.x+2,r.y+2],[r.right-2,r.y+2],[r.x+2,r.bottom-2],[r.right-2,r.bottom-2]]),quarters:hits([[r.x+r.width/2,r.y+r.height/2],...[.25,.75].flatMap(x=>[.25,.75].map(y=>[r.x+r.width*x,r.y+r.height*y]))])}}
   const original=inspect();n.style.zIndex='auto';const withoutLayerOverride=inspect();return {original,withoutLayerOverride}
  });await writeFile(resolve(directory,'close-hit-diagnostic.json'),JSON.stringify(diagnostic,null,2));await dialog.locator('button[value=cancel]').click()
 }else if(!reviewOnly){
  const before=await draft();await openDialog('image');stage='image-layout';await inspect('image')
  await dialog.locator('button[value=cancel]').click();await openDialog('gradient');stage='gradient-layout';await inspect('gradient')
  if(baseline){await dialog.locator('button[value=cancel]').click();assert.deepEqual(await draft(),before);assert.equal(saveCount,0);await writeFile(resolve(directory,'baseline.json'),JSON.stringify({layout,saveCount,errors,manifest},null,2))}
  else{
   assert.deepEqual(layout.failures,[])
   for(const close of ['cancel','escape','title']){
    if(close==='cancel')await dialog.locator('button[value=cancel]').click()
    else if(close==='escape')await page.keyboard.press('Escape')
    else await dialog.getByRole('button',{name:'关闭设置背景格式',exact:true}).click()
    await dialog.waitFor({state:'hidden'});assert.equal(await opener('gradient').evaluate(n=>n===document.activeElement),true);assert.deepEqual(await draft(),before)
    await openDialog('gradient');assert.equal(await dialog.getByLabel('渐变起始颜色',{exact:true}).inputValue(),'#ffffff')
   }
   await dialog.locator('button[value=cancel]').click();await openDialog('image');stage='invalid-image';await choose(resolve(directory,'invalid.png'))
   await dialog.getByRole('alert').filter({hasText:'请选择有效的 PNG 或 JPEG 图片'}).waitFor();await inspect('invalid-image-error');assert.deepEqual(layout.failures,[]);assert.deepEqual(await draft(),before)
   await dialog.locator('button[value=cancel]').click();await openDialog('image');stage='cancel-pending'
   const waiting=page.waitForEvent('filechooser');await dialog.locator('button[value=ok]').click();const chooser=await waiting
   assert.equal(await dialog.locator('button[value=ok]').isDisabled(),true);assert.equal(await dialog.locator('button[value=reset]').isDisabled(),true)
   await inspect('pending');assert.deepEqual(layout.failures,[]);await dialog.locator('button[value=cancel]').click();await chooser.setFiles(resolve(directory,'background.png'))
   await page.waitForFunction(()=>!document.querySelector('input[type=file]'));assert.deepEqual(await draft(),before)
   stage='image-all';await openDialog('image');await dialog.getByLabel('背景图片填充方式',{exact:true}).selectOption('tile');await dialog.locator('[name=all]').check();await dialog.locator('[name=graphics]').check();await choose(resolve(directory,'background.png'));await dialog.waitFor({state:'hidden'});let applied=await history('image-all',before)
   assert.deepEqual(applied[0].backgroundImages.map(({slideIndices,tile})=>({slideIndices,tile})),[{slideIndices:[0,1,2],tile:true}])
   stage='gradient-second';await selectSlide(1);await openDialog('gradient');await dialog.getByLabel('渐变起始颜色',{exact:true}).fill('#ff8800');await dialog.getByLabel('渐变结束颜色',{exact:true}).fill('#004488');await dialog.getByLabel('渐变方向',{exact:true}).selectOption('2');await dialog.locator('[name=graphics]').uncheck();const prior=await draft();await dialog.locator('button[value=ok]').click();applied=await history('gradient-second',prior)
   assert.deepEqual(applied[0].backgroundGradients,[{slideIndices:[1],from:'#FF8800',to:'#004488',angleDeg:45,radial:false}])
   stage='reset-third';await selectSlide(2);await openDialog('image');const previous=await draft();await dialog.locator('button[value=reset]').click();applied=await history('reset-third',previous)
   assert.deepEqual(applied[0].backgroundResets,[2]);assert.deepEqual(applied[0].backgroundImages.map(x=>x.slideIndices),[[0]])
   await page.reload();await page.locator('.slides-canvas canvas').first().waitFor({timeout:60000});await waitDraft(applied)
   stage='save';await page.locator('[data-action=save]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存，存在告警',null,{timeout:120000});assert.equal(routeError,undefined)
   const warning=await page.getByText('背景版式待复核，文件已生成。',{exact:false}).innerText();await writeFile(resolve(directory,'save-warning.json'),JSON.stringify({warning,saveCount},null,2))
  }
 }
 if(!baseline){
  stage='download';const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('link',{name:'下载 PPTX',exact:true}).click()]);assert.equal(await download.failure(),null);const bytes=await readFile(await download.path());assert.equal(sha(bytes),saved.sha256);await writeFile(resolve(directory,'downloaded.pptx'),bytes)
  const independent=engine({mode:'verify'});await writeFile(resolve(directory,'independent-check.json'),JSON.stringify(independent,null,2))
  stage='reopen';await open(2);assert.deepEqual(await draft(),[])
  await openDialog('image');assert.equal(await dialog.getByLabel('背景图片填充方式',{exact:true}).inputValue(),'tile');assert.equal(await dialog.locator('[name=graphics]').isChecked(),true);await inspect('reopened-image');await dialog.locator('button[value=cancel]').click()
  await selectSlide(1);await openDialog('gradient');assert.equal(await dialog.getByLabel('渐变起始颜色',{exact:true}).inputValue(),'#ff8800');assert.equal(await dialog.getByLabel('渐变结束颜色',{exact:true}).inputValue(),'#004488');assert.equal(await dialog.getByLabel('渐变方向',{exact:true}).inputValue(),'2');assert.equal(await dialog.locator('[name=graphics]').isChecked(),false);await inspect('reopened-gradient');await dialog.locator('button[value=cancel]').click()
  const context=await page.evaluate(async()=>(await(await fetch(location.pathname+'/api/context')).json()).context);assert.equal(context.revision,2);assert.equal(context.sourceFile.sha256,saved.sha256)
  assert.deepEqual(layout.failures,[]);await writeFile(resolve(directory,'reopened-context.json'),JSON.stringify(context,null,2))
 }
 await Promise.all(checks);assert.deepEqual(errors,[]);assert.equal(routeError,undefined);assert.equal(sha(await readFile(resolve(staticRoot,'.vite/manifest.json'))),manifest)
 for(const name of scripts)assert.equal(sha(await readFile(resolve(frontend,'smoke',name))),hashes[name])
 for(const name of Object.keys(bridgeHashes))assert.equal(sha(await readFile(resolve(repo,'smart_reporting/reporting/slides_engine/dist',name))),bridgeHashes[name])
 const result={ok:!baseline,baseline,reviewOnly,saveCount,directory,layout,steps,manifest,bridgeHashes,scriptHashes:hashes,resources:Object.fromEntries(resources),errors,routeIsFixture:true,previewPdfNotTested:true};await writeFile(resolve(directory,baseline?'baseline.json':'evidence.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({baseline,saveCount,cases:layout.cases.length,failures:layout.failures.length,resources:resources.size}))
}catch(e){await page?.screenshot({path:resolve(directory,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(resolve(directory,'failure.json'),JSON.stringify({stage,saveCount,error:String(e),stack:e.stack,errors,routeError},null,2));throw e}
finally{await browser?.close();await new Promise(resolve=>server.close(resolve))}
