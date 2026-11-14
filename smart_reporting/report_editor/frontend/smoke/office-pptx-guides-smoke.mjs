// 冻结前端完整宿主；授权与修订登记为显式夹具，文档渲染和保存调用真实Python/Node引擎。
import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {readFile,writeFile,mkdir,readdir} from 'node:fs/promises'
import {createServer} from 'node:http'
import {spawnSync} from 'node:child_process'
import {resolve,extname} from 'node:path'
import {fileURLToPath} from 'node:url'
import {chromium} from 'playwright'
import AxeBuilder from '@axe-core/playwright'
import {inspectPptxSettingsLayout} from './office-pptx-settings-layout.mjs'
import {inspectSizeLayout} from './office-pptx-size-layout.mjs'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=resolve(frontend,'../../..')
const directory=process.env.PPTX_GUIDES_DIRECTORY,staticRoot=process.env.PPTX_GUIDES_STATIC
const readOnly=process.env.PPTX_GUIDES_READ_ONLY==='1'
assert.ok(directory&&staticRoot,'显式指定构建和证据目录');await mkdir(directory,{recursive:true})
const entries=await readdir(directory)
assert.equal(entries.some(n=>/^(?:saved|revision-2|downloaded)/.test(n)),false,'禁止重放已成功保存的来源')
const sha=b=>createHash('sha256').update(b).digest('hex'),manifest=sha(await readFile(resolve(staticRoot,'.vite/manifest.json')))
assert.equal(manifest,process.env.PPTX_GUIDES_EXPECTED_MANIFEST_SHA256)
const scripts=['office-pptx-guides-smoke.mjs','office-pptx-background-fixture.py','office-pptx-guides-verify.py','office-pptx-settings-layout.mjs','office-pptx-size-layout.mjs','slides-dialog-input-protection.mjs'],hashes={}
for(const name of scripts)hashes[name]=sha(await readFile(resolve(frontend,'smoke',name)))
const bridgeHashes={};for(const name of ['edit-pptx.mjs','render-pptx.mjs'])bridgeHashes[name]=sha(await readFile(resolve(repo,'smart_reporting/reporting/slides_engine/dist',name)))
const engine=p=>{const r=spawnSync(resolve(repo,'.venv/bin/python'),[resolve(frontend,'smoke/office-pptx-background-fixture.py')],{cwd:repo,env:{...process.env,PYTHONPATH:repo,TMPDIR:'/dev/shm',PYTHONDONTWRITEBYTECODE:'1'},input:JSON.stringify({directory,...p}),encoding:'utf8',maxBuffer:20*1024*1024,timeout:120000});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout)}
const file=n=>resolve(directory,`revision-${n}.pptx`),revisions={1:engine(entries.includes('revision-1.pptx')?{mode:'inspect',source:file(1)}:{mode:'create'})}
let saved,saveCount=0,saveAttempted=false,saveRequests=0,downloadEvents=0,browser,page,stage='setup',routeError,manualOps,settings
const sizeLayout={cases:[],failures:[]}
const docId='guides-pc',prefix='/reports/v1/editor/assets/',layout={cases:[],failures:[]},pointerFocus=[],errors=[],checks=[],resources=new Map()
const server=createServer(async(req,res)=>{try{
 const path=new URL(req.url,'http://localhost').pathname
 if(path==='/favicon.ico'){res.writeHead(204);res.end();return}
 if(path==='/download/2.pptx'){assert.ok(saved);const bytes=await readFile(file(2));res.writeHead(200,{'Content-Type':'application/vnd.openxmlformats-officedocument.presentationml.presentation','Content-Disposition':'attachment; filename=guides.pptx','Content-Length':bytes.length});res.end(bytes);return}
 assert.ok(path.startsWith(prefix));const target=resolve(staticRoot,path.slice(prefix.length));assert.ok(target.startsWith(staticRoot+'/'));const bytes=await readFile(target)
 res.writeHead(200,{'Content-Type':{'.js':'application/javascript','.css':'text/css','.html':'text/html','.woff2':'font/woff2','.wasm':'application/wasm'}[extname(target)]??'application/octet-stream'});res.end(bytes)
 }catch{res.writeHead(404);res.end('not found')}})
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const base=`http://127.0.0.1:${server.address().port}`,pathBase=`/reports/v1/native/${docId}/`
try{
 browser=await chromium.launch({headless:true});const context=await browser.newContext({viewport:{width:1440,height:900},acceptDownloads:true});page=await context.newPage()
 page.on('download',()=>{downloadEvents++})
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
  assert.ok(path.endsWith('/save'));saveRequests++;assert.equal(readOnly,false,'只读宿主禁止保存');assert.equal(saveAttempted,false,'只能保存一次');assert.equal(n,1);saveAttempted=true
  revisions[2]=engine({mode:'patch',source:file(1),output:file(2),operations:post.operations});saved={...revisions[2],operations:post.operations};delete saved.model
  saveCount++;await writeFile(resolve(directory,'saved.json'),JSON.stringify(saved,null,2))
  return route.fulfill({json:{documentId:docId,revision:2,parentRevision:1,revisionRegistered:true,artifacts:{pptx:{downloadUrl:base+'/download/2.pptx',size:saved.size,sha256:saved.sha256}},editor:{openUrl:pathBase+'2'},validation:{ok:false,issues:[{code:'manual_review',message:'参考线专项验收待复核，文件已生成。'}]}}})
 }catch(e){routeError=String(e);await route.fulfill({status:500,json:{detail:routeError}})}})
 const open=async n=>{await page.goto(base+pathBase+n);await page.locator('.slides-canvas canvas').first().waitFor({timeout:60000})}
 const draft=()=>page.evaluate(()=>Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).flatMap(([,value])=>JSON.parse(value).operations))
 const snapshot=async()=>JSON.stringify(await draft())
 const beforeView=await open(1).then(snapshot)
 const guidesStorage=()=>page.evaluate(()=>Object.entries(localStorage).filter(([key])=>key.startsWith('native-slides-guides:')))
 const viewTab=page.locator('[data-ribbon-tab=view]')
 await viewTab.click()
 await page.locator('[data-command=ruler]').click();await page.locator('[data-command=guides]').click()
 await page.locator('.guide-v').first().waitFor()
 const initialGuides=await page.locator('.guide-draggable').evaluateAll(nodes=>nodes.map(node=>({axis:node.classList.contains('guide-v')?'v':'h',pos:Number(node.getAttribute('aria-valuenow'))/100})))
 assert.deepEqual(initialGuides,[{axis:'v',pos:.5},{axis:'h',pos:.5}])
 for(const viewport of [{width:1440,height:900},{width:640,height:360},{width:390,height:320},{width:320,height:640}]){
  stage=`layout-${viewport.width}x${viewport.height}`;await page.setViewportSize(viewport);await viewTab.click()
  const controls=[]
  for(const command of ['ruler','guides']){
   const button=page.locator(`[data-command=${command}]`)
   await button.focus()
   const measured=await button.evaluate(node=>{const rect=node.getBoundingClientRect(),hit=document.elementFromPoint(rect.x+rect.width/2,rect.y+rect.height/2);return {x:rect.x,y:rect.y,width:rect.width,height:rect.height,pressed:node.getAttribute('aria-pressed'),hit:!!hit&&(node===hit||node.contains(hit))}})
   assert.ok(measured.x>=0&&measured.y>=0&&measured.x+measured.width<=viewport.width+1&&measured.y+measured.height<=viewport.height+1&&measured.hit,JSON.stringify({command,viewport,measured}))
   assert.equal(measured.pressed,'true');controls.push({command,...measured})
  }
  const add=page.getByRole('button',{name:'+ 添加垂直参考线',exact:true})
  await add.focus();await page.keyboard.press('Enter')
  await page.locator('.guide-v').last().focus()
  const protectedKeys=await page.evaluate(()=>{
   const line=document.activeElement,before=line.getAttribute('aria-valuenow'),storage=JSON.stringify(localStorage),records=[]
   for(const key of ['ArrowLeft','ArrowRight','Home','End','Delete','Backspace'])for(const protection of ['composition','legacy','handled']){
    const event=new KeyboardEvent('keydown',{key,bubbles:true,cancelable:true,isComposing:protection==='composition',keyCode:protection==='legacy'?229:0});if(protection==='handled')event.preventDefault();line.dispatchEvent(event)
    records.push({key,protection,preserved:line.isConnected&&line.getAttribute('aria-valuenow')===before&&JSON.stringify(localStorage)===storage,focused:line===document.activeElement,prevented:event.defaultPrevented})
   }return records
  })
  for(const record of protectedKeys)assert.ok(record.preserved&&record.focused&&record.prevented===(record.protection==='handled'),JSON.stringify(record))
  await page.keyboard.press('ArrowRight');await page.keyboard.press('Shift+ArrowLeft')
  await page.keyboard.press('Delete')
  assert.deepEqual(JSON.parse((await guidesStorage())[0][1]),initialGuides)
  assert.equal(await snapshot(),beforeView)
  const canvas=await page.locator('.slides-canvas').first().evaluate(node=>{const rect=node.getBoundingClientRect();return {x:rect.x,y:rect.y,width:rect.width,height:rect.height,viewportWidth:innerWidth,viewportHeight:innerHeight}})
  assert.ok(canvas.height>=120,JSON.stringify({reason:'备注展开时画布必须保留可用的120px区域，备注通过工作区滚动访问',viewport,canvas}))
  const axe=await new AxeBuilder({page}).include('.slides-native-ribbon').include('.slides-stage').analyze()
  const observation={viewport,controls,canvas,axe:axe.violations,protectedKeys};layout.cases.push(observation);assert.deepEqual(axe.violations,[])
  await page.screenshot({path:resolve(directory,`editor-${viewport.width}x${viewport.height}.png`),fullPage:true})
  const notes=page.getByRole('textbox',{name:'演讲者备注',exact:true});await notes.click()
  observation.notes=await notes.evaluate(node=>{const rect=node.getBoundingClientRect(),hit=document.elementFromPoint(rect.x+rect.width/2,rect.y+rect.height/2);return {x:rect.x,y:rect.y,height:rect.height,hit:hit===node,focused:document.activeElement===node}})
  assert.ok(observation.notes.hit&&observation.notes.focused,JSON.stringify(observation.notes))
  const reason=page.locator('.slides-notes-reason')
  assert.equal(await reason.innerText(),'备注母版结构暂不支持编辑；可查看或复制现有备注。')
  assert.equal(await notes.evaluate(node=>node.ownerDocument.getElementById(node.getAttribute('aria-describedby'))?.textContent),await reason.innerText())
  assert.equal(await notes.getAttribute('readonly')!==null,true)
  const originalNotes=await notes.inputValue()
  await page.keyboard.press('ControlOrMeta+a')
  assert.equal(await notes.evaluate(node=>node.selectionEnd-node.selectionStart),originalNotes.length)
  await page.keyboard.type('不得覆盖只读备注')
  assert.equal(await notes.inputValue(),originalNotes)
  await reason.scrollIntoViewIfNeeded()
  observation.notes.reason=await reason.innerText()
  observation.notes.readOnlyPreserved=true
  await page.screenshot({path:resolve(directory,`notes-reason-${viewport.width}x${viewport.height}.png`),fullPage:true})
  await page.getByRole('button',{name:'收起备注',exact:true}).click()
  assert.equal(await notes.isVisible(),false)
  await viewTab.click();await page.locator('[data-command=notes]').click();assert.equal(await notes.isVisible(),true)
  assert.equal(await snapshot(),beforeView)
  await page.locator('.slides-workspace,.slides-stage,.slides-canvas').evaluateAll(nodes=>nodes.forEach(node=>node.scrollTo(0,0)))
 }
 stage='desktop-drag';await page.setViewportSize({width:1440,height:900})
 if(process.env.PPTX_GUIDES_POINTER_FOCUS==='1'){
  for(const axis of ['v','h'])for(const gesture of ['click','drag']){
   stage=`pointer-focus-${axis}-${gesture}`
   await page.getByRole('textbox',{name:'演讲者备注',exact:true}).focus()
   const guide=page.locator(`.guide-${axis}`).first();await guide.scrollIntoViewIfNeeded()
   await guide.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))
   const canvas=await page.locator('.konvajs-content').first().boundingBox(),grip=await guide.boundingBox(),original=Number(await guide.getAttribute('aria-valuenow'))/100
   const x=axis==='v'?grip.x+grip.width/2:canvas.x+canvas.width*.25,y=axis==='h'?grip.y+grip.height/2:canvas.y+canvas.height*.25
   await page.mouse.move(x,y);await page.mouse.down();const capture=await guide.evaluate(node=>node.hasPointerCapture(1));assert.equal(capture,true)
   if(gesture==='drag')await page.mouse.move(axis==='v'?canvas.x+canvas.width*.6:x,axis==='h'?canvas.y+canvas.height*.6:y,{steps:5})
   await page.mouse.up();assert.equal(await guide.evaluate(node=>document.activeElement===node),true)
   const before=Number(await guide.getAttribute('aria-valuenow')),length=revisions[1].model.size[axis==='v'?'cx':'cy']/9525
   await page.keyboard.press(axis==='v'?'ArrowRight':'ArrowDown');const after=Number(await guide.getAttribute('aria-valuenow'))
   assert.ok(Math.abs(after-before-100/length)<.002,JSON.stringify({axis,gesture,before,after,length}))
   await page.keyboard.press(axis==='v'?'ArrowLeft':'ArrowUp');assert.ok(Math.abs(Number(await guide.getAttribute('aria-valuenow'))-before)<.002)
   if(gesture==='drag'){
    const current=await guide.boundingBox();await page.mouse.move(axis==='v'?current.x+current.width/2:x,axis==='h'?current.y+current.height/2:y);await page.mouse.down()
    await page.mouse.move(axis==='v'?canvas.x+canvas.width*original:x,axis==='h'?canvas.y+canvas.height*original:y,{steps:5});await page.mouse.up()
   }
   assert.equal(await snapshot(),beforeView);pointerFocus.push({axis,gesture,capture,focused:true,canvas,before,after,original,documentDraftUnchanged:true})
  }
  stage='desktop-drag'
 }
 const line=page.locator('.guide-v').first(),lineBox=await line.boundingBox(),host=await page.locator('.konvajs-content').first().boundingBox()
 const beforeDrag=await guidesStorage(),protectedDrags=[]
 await page.mouse.move(lineBox.x+lineBox.width/2,host.y+host.height*.25);await page.mouse.down();await page.mouse.move(host.x+host.width*.6,host.y+host.height*.25,{steps:5})
 const preview=await line.getAttribute('aria-valuenow')
 for(const protection of ['composition','legacy','handled']){
  await page.evaluate(protection=>{const event=new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true,isComposing:protection==='composition',keyCode:protection==='legacy'?229:0});if(protection==='handled')event.preventDefault();window.dispatchEvent(event)},protection)
  assert.equal(await line.getAttribute('aria-valuenow'),preview);assert.deepEqual(await guidesStorage(),beforeDrag);assert.equal(await page.locator('.ruler-bubble').isVisible(),true);protectedDrags.push(protection)
 }
 await page.evaluate(()=>window.addEventListener('keydown',event=>event.preventDefault(),{capture:true,once:true}));await page.keyboard.press('Escape');assert.equal(await line.getAttribute('aria-valuenow'),preview)
 await page.keyboard.press('Escape');await page.mouse.up();assert.deepEqual(await guidesStorage(),beforeDrag);assert.equal(await line.getAttribute('aria-valuenow'),'50')
 await page.mouse.move(lineBox.x+lineBox.width/2,host.y+host.height*.25);await page.mouse.down();await page.mouse.move(host.x+host.width*.65,host.y+host.height*.25,{steps:5});await page.mouse.up()
 assert.ok(Math.abs(JSON.parse((await guidesStorage())[0][1])[0].pos-.65)<.02)
 const stored=await guidesStorage();assert.equal(await snapshot(),beforeView)
 await page.locator('.slide-row').nth(1).locator('.slide-open').click();await page.locator('.slide-row').first().locator('.slide-open').click()
 assert.deepEqual(await guidesStorage(),stored);assert.equal(await snapshot(),beforeView)
 stage='reload';await page.reload();await page.locator('.slides-canvas canvas').first().waitFor();await viewTab.click()
 await page.locator('[data-command=ruler]').click();await page.locator('[data-command=guides]').click()
 assert.deepEqual(await guidesStorage(),stored);assert.equal(await snapshot(),beforeView)
 if(readOnly){
  stage='read-only-settings'
  settings=await inspectPptxSettingsLayout(page,{viewports:'1440x900,320x640,640x360,390x320',output:directory,draft})
  await page.setViewportSize({width:1440,height:900});await page.locator('[data-ribbon-tab=design]').click()
  const opener=page.locator('[data-command=customSlideSize]');await opener.click()
  await inspectSizeLayout(page,{output:directory,phase:'read-only',layout:sizeLayout,draft});assert.deepEqual(sizeLayout.failures,[])
  sizeLayout.escapeCases=[]
  for(const [width,height] of [[1440,900],[320,640],[640,360],[390,320]]){
   await page.setViewportSize({width,height});await page.keyboard.press('Escape')
   await page.getByRole('dialog',{name:'自定义幻灯片尺寸',exact:true}).waitFor({state:'detached'})
   assert.equal(await opener.evaluate(node=>document.activeElement===node),true);assert.equal(await snapshot(),beforeView)
   sizeLayout.escapeCases.push({width,height,openerRestored:true,draftUnchanged:true})
   if(width!==390)await opener.click()
  }
  assert.equal(await snapshot(),beforeView);assert.equal(saveRequests,0);assert.equal(downloadEvents,0)
  assert.equal(sha(await readFile(file(1))),revisions[1].sha256)
  await page.screenshot({path:resolve(directory,'read-only-final.png'),fullPage:true})
 }else{
 // 唯一文档变更作为保存哨兵；参考线操作不得出现在operations中。
 stage='sentinel-edit';const expected='参考线专项保存哨兵 PC'
 await page.locator('#object-text').fill(expected)
 await page.waitForFunction(()=>Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).flatMap(([,value])=>JSON.parse(value).operations).length>0)
 manualOps=await draft();await writeFile(resolve(directory,'manual-operations.json'),JSON.stringify(manualOps,null,2))
 await page.locator('.guide-v').first().focus();await page.keyboard.press('ArrowRight');await page.keyboard.press('ArrowLeft')
 await page.locator('[data-command=ruler]').click();await page.locator('[data-command=ruler]').click()
 assert.deepEqual(await draft(),manualOps)
 stage='save';await page.locator('[data-action=save]').click()
 await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存，存在告警',null,{timeout:120000});if(routeError)throw Error(routeError)
 assert.equal(saveCount,1);assert.deepEqual(saved.operations,manualOps)
 await page.getByText('参考线专项验收待复核，文件已生成。',{exact:false}).waitFor()
 const downloading=page.waitForEvent('download');await page.getByRole('link',{name:'下载 PPTX',exact:true}).click();const download=await downloading
 assert.equal(await download.failure(),null);await download.saveAs(resolve(directory,'downloaded.pptx'));assert.equal(sha(await readFile(resolve(directory,'downloaded.pptx'))),saved.sha256)
 stage='reopen';await open(2);assert.equal(await page.locator('#object-text').inputValue(),expected)
 await viewTab.click();await page.locator('[data-command=ruler]').click();await page.locator('[data-command=guides]').click()
 const recovered=JSON.parse((await guidesStorage())[0][1]);assert.ok(Math.abs(recovered[0].pos-.65)<.02)
 await page.screenshot({path:resolve(directory,'reopened.png'),fullPage:true})
 }
 stage='dispose';await page.evaluate(()=>window.dispatchEvent(new PageTransitionEvent('pagehide',{persisted:false})))
 await page.waitForTimeout(500);assert.equal(await page.locator('.ruler,.ruler-corner,.guide-line,.ruler-bubble').count(),0)
 await Promise.all(checks);assert.deepEqual(errors,[])
 for(const [name,hash] of Object.entries(bridgeHashes))assert.equal(sha(await readFile(resolve(repo,'smart_reporting/reporting/slides_engine/dist',name))),hash)
 await writeFile(resolve(directory,'evidence.json'),JSON.stringify({ok:true,readOnly,scope:readOnly?'frozen frontend native host; fixture authorization/context; real Python/Node inspect/render; no save or download':'frozen frontend native host; fixture authorization/revision registry; real Python/Node preview and save',manifest,hashes,bridgeHashes,sourceSha256:revisions[1].sha256,sourceUnchanged:sha(await readFile(file(1)))===revisions[1].sha256,outputSha256:saved?.sha256,manualOps,pointerFocus,protectedDrags,viewOnlyDraftUnchanged:true,saveCount,saveRequests,saveAttempted,downloadEvents,actualDownload:!readOnly,reopened:!readOnly,syntheticPagehideCleanup:true,layout,settings,sizeLayout,resources:Object.fromEntries(resources),errors},null,2))
 console.log(JSON.stringify({ok:true,cases:layout.cases.length,resources:resources.size}))
}catch(error){await page?.screenshot({path:resolve(directory,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(resolve(directory,'failure.json'),JSON.stringify({stage,readOnly,saveCount,saveRequests,saveAttempted,downloadEvents,error:String(error),stack:error.stack,errors,routeError,layout,settings,sizeLayout},null,2));throw error}
finally{await browser?.close();await new Promise(done=>server.close(done))}
