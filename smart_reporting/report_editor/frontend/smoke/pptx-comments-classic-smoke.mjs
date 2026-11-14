// API routes 为显式 fixture；inspect/preview/save/render 均运行生产 Python/Node 引擎。
// 真实 ZIP/lxml 文件夹具与独立回读使用仓库的专属测试 helper。
import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {readFile,writeFile,mkdir} from 'node:fs/promises'
import {createServer} from 'node:http'
import {spawnSync} from 'node:child_process'
import {dirname,resolve,extname} from 'node:path'
import {fileURLToPath} from 'node:url'
import {chromium} from 'playwright'
import {verifyBrowserTextInput} from './browser-input-preflight.mjs'
import {commentsLongText,commentsLongAuthor,inspectPptxCommentsLayout} from './office-pptx-comments-layout.mjs'
const frontend=resolve(dirname(fileURLToPath(import.meta.url)),'..'),repo=resolve(frontend,'../../..'),staticRoot=resolve(process.env.PPTX_COMMENTS_STATIC_ROOT??resolve(frontend,'../static'))
const helper=process.env.PPTX_COMMENTS_FIXTURE_SCRIPT??resolve(repo,'smart_reporting/reporting/tests/pptx_comments_fixture.py')
const output=process.env.PPTX_COMMENTS_EVIDENCE??'/tmp/pptx-comments-built-20261111',port=Number(process.env.PPTX_COMMENTS_PORT??4311)
const mode=process.env.PPTX_COMMENTS_MODE??'classic';assert.ok(['classic','boundaries'].includes(mode))
const sha=b=>createHash('sha256').update(b).digest('hex'),manifestSha256=sha(await readFile(resolve(staticRoot,'.vite/manifest.json')))
assert.equal(manifestSha256,process.env.PPTX_EXPECTED_MANIFEST_SHA256);await mkdir(output,{recursive:true})
const bridgePath=resolve(process.env.AGENT_REPORTING_SLIDES_ENGINE_DIR??resolve(repo,'smart_reporting/reporting/slides_engine'),'dist/edit-pptx.mjs'),nodeBridgeSha256=sha(await readFile(bridgePath)),fixtureScriptSha256=sha(await readFile(helper))
function engine(payload){const r=spawnSync(resolve(repo,'.venv/bin/python'),[helper],{cwd:repo,env:{...process.env,PYTHONPATH:repo},input:JSON.stringify(payload),encoding:'utf8',maxBuffer:30*1024*1024,timeout:120000});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout)}
const variants=mode==='classic'?['classic']:['modern','broken'],sources={}
for(const variant of variants){const path=resolve(output,variant+'-revision-1.pptx'),created=engine({mode:'create',variant,path,...(process.env.PPTX_COMMENTS_LAYOUT_VIEWPORTS?{longText:commentsLongText,longAuthor:commentsLongAuthor}:{})}),entry=engine({mode:'inspect',path});sources[variant]={path,readback:created.readback,...entry};await writeFile(resolve(output,variant+'-source-readback.json'),JSON.stringify(created.readback,null,2))}
const requests=[],pageErrors=[],consoleErrors=[],failedResponses=[],chunks=new Map(),identities=[],routeErrors=[]
let browser,page,payload,verified,downloaded,active=sources[variants[0]],revision=1
const base='http://127.0.0.1:'+port,documentId='fixture-pptx-classic-comments',pathBase='/reports/v1/native/'+documentId+'/'
const server=createServer(async(req,res)=>{try{const path=new URL(req.url,base).pathname,file=resolve(staticRoot,path.replace(/^\/reports\/v1\/editor\/assets\//,''));assert.ok(file.startsWith(staticRoot+'/'));const bytes=await readFile(file);res.writeHead(200,{'Content-Type':extname(file)==='.js'?'application/javascript':extname(file)==='.css'?'text/css':extname(file)==='.woff2'?'font/woff2':'text/html'});res.end(bytes)}catch{res.writeHead(404);res.end('not found')}})
await new Promise((done,reject)=>{server.once('error',reject);server.listen(port,'127.0.0.1',done)})
const mediaType='application/vnd.openxmlformats-officedocument.presentationml.presentation'
const newTexts=['历史恢复的中文根批注😀 <&> "引号"','未失焦保存的根批注😀 & <完成>']
try{
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})})
 const inputBaseline=await verifyBrowserTextInput(browser)
 page=await browser.newPage({viewport:{width:1600,height:1100},acceptDownloads:true})
 page.on('pageerror',e=>pageErrors.push(e.message));page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text())})
 page.on('response',r=>{const path=new URL(r.url()).pathname;if(r.status()>=400)failedResponses.push({path,status:r.status()});if(r.ok()&&path.endsWith('.js'))identities.push(r.body().then(async bytes=>{const disk=await readFile(resolve(staticRoot,path.replace(/^\/reports\/v1\/editor\/assets\//,'')));assert.equal(sha(bytes),sha(disk),path);chunks.set(path,{path,size:bytes.length,sha256:sha(bytes)})}))})
 await page.route('**/favicon.ico',route=>route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg"/>'}))
 await page.route('**/reports/v1/native/'+documentId+'/*/api/**',async route=>{
  try{
   const request=route.request(),path=new URL(request.url()).pathname,post=request.method()==='POST'?request.postDataJSON():undefined;requests.push({path,method:request.method(),payload:post})
   if(path.endsWith('/context'))return route.fulfill({json:{context:{documentId,format:'pptx',revision,parentRevision:revision===1?null:1,scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},sourceFile:{path:'revision-'+revision+'.pptx',size:Buffer.from(active.bytes,'base64').length,sha256:active.model.sha256,mediaType},origin:'upload'},csrfToken:'fixture-only-csrf',capabilities:{pptx_editor:true},editingEnabled:true}})
   if(path.endsWith('/file'))return route.fulfill({body:Buffer.from(active.bytes,'base64'),contentType:mediaType})
   if(path.endsWith('/preview.pdf'))return route.fulfill({contentType:'application/pdf',body:'%PDF-1.4\n%%EOF'})
   if(post)assert.equal(post.expectedSha256,active.model.sha256)
   const operations=post?.operations??[]
   if(path.endsWith('/render-tree'))return route.fulfill({json:engine({mode:'render',path:active.path,operations})})
   if(path.endsWith('/preview')){
    const result=operations.length?engine({mode:'patch',path:active.path,output:resolve(output,'preview.pptx'),operations}):active
    return route.fulfill({json:{sourceSha256:active.model.sha256,draftSha256:result.model.sha256,model:result.model}})
   }
   if(path.endsWith('/save')){
    assert.equal(mode,'classic');assert.equal(payload,undefined,'do not repeat successful save')
    assert.equal(revision,1);assert.equal(operations.length,1);assert.equal(operations[0].kind,'editSlides')
    const edits=operations[0].commentEdits;assert.equal(edits.length,4)
    assert.deepEqual(edits.filter(e=>e.kind==='delete'),[{slideIndex:0,kind:'delete',authorId:0,idx:1},{slideIndex:1,kind:'delete',authorId:0,idx:2}])
    assert.deepEqual(edits.filter(e=>e.kind==='add').map(e=>({slideIndex:e.slideIndex,text:e.text})),newTexts.map(text=>({slideIndex:0,text})))
    assert.ok(edits.every(e=>!('author' in e)&&!('commentAuthor' in e)))
    for(const key of Object.keys(operations[0]))if(!['kind','commentEdits','order'].includes(key))assert.deepEqual(operations[0][key],[],key)
    assert.deepEqual(operations[0].order,[0,1])
    const result=engine({mode:'patch',path:active.path,output:resolve(output,'revision-2.pptx'),operations});payload=post;downloaded=result
    verified=engine({mode:'verify',source:active.path,output:resolve(output,'revision-2.pptx'),expected:newTexts})
    await writeFile(resolve(output,'saved-request.json'),JSON.stringify(post,null,2));await writeFile(resolve(output,'zip-lxml-verification.json'),JSON.stringify(verified,null,2))
    return route.fulfill({json:{documentId,revision:2,parentRevision:1,revisionRegistered:true,artifacts:{pptx:{downloadUrl:'/pptx-classic-comments-download.pptx',size:Buffer.from(result.bytes,'base64').length,sha256:result.model.sha256}},editor:{openUrl:pathBase+'2'},validation:{ok:false,issues:[{code:'fixture_comments_review_pending',message:'经典批注版式待人工复核'}]}}})
   }
   throw new Error('unexpected comments API '+path)
  }catch(error){routeErrors.push(error.message);return route.fulfill({status:500,json:{detail:error.message}})}
 })
 await page.route('**/pptx-classic-comments-download.pptx',route=>route.fulfill({body:Buffer.from(downloaded.bytes,'base64'),contentType:mediaType}))
 await page.route(/\/reports\/v1\/native\/fixture-pptx-classic-comments\/\d+$/,async route=>route.fulfill({body:await readFile(resolve(staticRoot,'native.html')),contentType:'text/html'}))
 const open=async()=>{await page.goto(base+pathBase+revision);await page.locator('.slides-native-ribbon').waitFor({timeout:60000});await page.locator('.slides-canvas canvas').first().waitFor({timeout:60000});await page.waitForFunction(()=>document.querySelector('.canvas-status')?.textContent.includes('点击对象选择'))}
 const draft=()=>page.evaluate(()=>{const k=Object.keys(localStorage).find(k=>k.startsWith('native-editor-draft:v1:'));return k?JSON.parse(localStorage.getItem(k)).operations:[]})
 const comments=async()=>{const op=(await draft())[0];return op?.commentEdits??[]}
 const pane=()=>page.locator('.slides-comments-pane'),input=()=>pane().locator('[data-comment-text]')
 const sourceCard=(authorId,idx)=>pane().locator('[data-comment-author-id="'+authorId+'"][data-comment-idx="'+idx+'"]')
 const openPane=async()=>{await page.locator('[data-ribbon-tab="review"]').click();await page.locator('[data-command="commentsPane"]').click();await pane().waitFor({state:'visible'})}
 const newComment=async()=>{await page.locator('[data-command="newComment"]').click();await input().waitFor({state:'visible'})}
 const undo=()=>page.locator('[data-source-action="onUndo"]').click(),redo=()=>page.locator('[data-source-action="onRedo"]').click()
 const auditRibbon=async()=>{for(const [command,label] of [['commentsPane','批注窗格'],['newComment','新建批注']]){const b=page.locator('[data-command="'+command+'"]');assert.equal(await b.locator('svg').count(),1);assert.equal(await b.locator('svg').getAttribute('aria-hidden'),'true');assert.ok((await b.textContent()).includes(label),await b.textContent())}}
 const boundaryEvidence=[],layoutEvidence=[],componentLayouts=[]
 const geometry=async label=>{const value=await pane().evaluate(el=>{const r=el.getBoundingClientRect();return{left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height,viewportWidth:innerWidth,scrollWidth:document.documentElement.scrollWidth}});assert.ok(value.width>0&&value.left>=0&&value.right<=value.viewportWidth+2,JSON.stringify(value));assert.ok(value.scrollWidth<=value.viewportWidth+2,JSON.stringify(value));layoutEvidence.push({label,...value})}
 if(mode==='boundaries'){
  for(const variant of variants){
   active=sources[variant];await page.evaluate(()=>localStorage.clear()).catch(()=>{});await open();await openPane();await auditRibbon()
   const state=active.model.slides[0].comments;assert.equal(typeof state.readOnlyReason,'string');assert.ok(state.readOnlyReason.trim());assert.ok((await pane().textContent()).includes(state.readOnlyReason));assert.equal(await page.locator('[data-command="newComment"]').isDisabled(),true)
   assert.equal(await pane().locator('[data-comment-action="delete"]:enabled').count(),0);assert.deepEqual(await draft(),[])
   if(process.env.PPTX_COMMENTS_LAYOUT_VIEWPORTS)componentLayouts.push(await inspectPptxCommentsLayout(page,{output,viewports:process.env.PPTX_COMMENTS_LAYOUT_VIEWPORTS,phase:variant,readonly:true,draft}))
   await geometry(variant+'-readonly');await page.screenshot({path:resolve(output,variant+'-readonly.png'),fullPage:true});boundaryEvidence.push({variant,readOnlyReason:state.readOnlyReason,items:state.items,sourceSha256:active.model.sha256})
  }
  assert.equal(payload,undefined);assert.ok(requests.every(r=>!r.path.endsWith('/save')))
 }else{
  assert.deepEqual(active.model.slides.map(s=>s.comments.items.map(c=>[c.authorId,c.idx,c.text])),active.readback.slides.map(s=>s.comments.map(c=>[c.authorId,c.idx,c.text])))
  assert.ok(active.model.slides.every(s=>s.comments.readOnlyReason===null))
  await open();await openPane();await auditRibbon()
  if(process.env.PPTX_COMMENTS_LAYOUT_VIEWPORTS)componentLayouts.push(await inspectPptxCommentsLayout(page,{output,viewports:process.env.PPTX_COMMENTS_LAYOUT_VIEWPORTS,phase:'classic',draft}))
  assert.ok((await sourceCard(0,1).textContent()).includes(active.readback.slides[0].comments[0].text));assert.ok((await sourceCard(1,1).textContent()).includes(active.readback.slides[0].comments[1].text))
  await page.locator('.slide-open').nth(1).click();assert.equal(await sourceCard(0,2).count(),1);assert.equal(await sourceCard(0,1).count(),0)
  await page.locator('.slide-open').nth(0).click();assert.equal(await sourceCard(0,1).count(),1)
  await pane().locator('[data-comment-action="close"]').click();await openPane();assert.deepEqual(await draft(),[])
  // 重排后当前页仍显示原始来源0，再撤销回原顺序，不把显示位置当作slideIndex。
  await page.locator('.slide-row').nth(0).getByRole('button',{name:'下移页面',exact:true}).click();assert.equal(await sourceCard(0,1).count(),1)
  assert.deepEqual((await draft())[0].order,[1,0]);await undo();assert.deepEqual(await draft(),[])
  await newComment();await input().fill('取消且不得入草稿');await pane().locator('[data-comment-action="cancel"]').click();assert.deepEqual(await draft(),[])
  await newComment();await input().fill('仅供撤回的新批注');await pane().locator('[data-comment-action="add"]').click();assert.equal((await comments()).length,1)
  await pane().locator('[data-comment-client-id] [data-comment-action="withdraw"]').click();assert.deepEqual(await comments(),[])
  await sourceCard(0,1).locator('[data-comment-action="delete"]').click();assert.deepEqual(await comments(),[{slideIndex:0,kind:'delete',authorId:0,idx:1}]);assert.equal(await sourceCard(1,1).count(),1)
  await undo();assert.equal(await sourceCard(0,1).count(),1);await redo();assert.equal(await sourceCard(0,1).count(),0)
  await page.locator('.slide-open').nth(1).click();await sourceCard(0,2).locator('[data-comment-action="delete"]').click();assert.equal(await sourceCard(0,2).count(),0)
  await page.locator('.slide-open').nth(0).click();await newComment();await input().fill(newTexts[0]);await pane().locator('[data-comment-action="add"]').click()
  const seeded=await comments();assert.equal(seeded.length,3);await undo();assert.equal((await comments()).length,2);await redo();assert.deepEqual(await comments(),seeded)
  await geometry('comments-draft-history');await page.screenshot({path:resolve(output,'comments-draft-history.png'),fullPage:true});await page.reload();await page.locator('.slides-canvas canvas').first().waitFor({timeout:60000});await page.waitForFunction(()=>document.querySelector('.canvas-status')?.textContent.includes('点击对象选择'));assert.deepEqual(await comments(),seeded)
  await openPane();await newComment();await input().fill(newTexts[1]);assert.equal(await input().evaluate(el=>document.activeElement===el),true)
  await page.screenshot({path:resolve(output,'comments-unblurred.png'),fullPage:true})
  await page.locator('[data-action="save"]').dispatchEvent('click');await page.getByRole('link',{name:'下载 PPTX',exact:true}).waitFor({state:'visible',timeout:60000})
  assert.ok((await page.locator('body').textContent()).includes('经典批注版式待人工复核'));const link=page.getByRole('link',{name:'下载 PPTX',exact:true});assert.equal(await link.count(),1)
  const bytes=Buffer.from(await page.evaluate(async()=>Array.from(new Uint8Array(await(await fetch('/pptx-classic-comments-download.pptx')).arrayBuffer()))));assert.equal(sha(bytes),downloaded.model.sha256);await writeFile(resolve(output,'downloaded.pptx'),bytes)
  verified=engine({mode:'verify',source:sources.classic.path,output:resolve(output,'downloaded.pptx'),expected:newTexts});await page.screenshot({path:resolve(output,'comments-delivery.png'),fullPage:true})
  active={...downloaded,path:resolve(output,'downloaded.pptx')};revision=2;await open();await openPane()
  const reopened=active.model.slides[0].comments.items;assert.equal(reopened.filter(c=>c.author==='用户').length,2);assert.equal(await sourceCard(1,1).count(),1);assert.equal(await sourceCard(0,1).count(),0)
  assert.ok((await pane().textContent()).includes(newTexts[1]));await page.locator('.slide-open').nth(1).click();assert.equal(active.model.slides[1].comments.items.length,0);assert.equal(await pane().locator('[data-comment-author-id]').count(),0)
  await page.screenshot({path:resolve(output,'comments-revision-2.png'),fullPage:true})
 }
 await page.waitForLoadState('networkidle');await Promise.all(identities);assert.deepEqual(routeErrors,[]);assert.deepEqual(pageErrors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(failedResponses,[])
 for(const entry of chunks.values()){const bytes=await readFile(resolve(staticRoot,entry.path.replace(/^\/reports\/v1\/editor\/assets\//,'')));assert.equal(sha(bytes),entry.sha256)}
 assert.equal(sha(await readFile(resolve(staticRoot,'.vite/manifest.json'))),manifestSha256)
 for(const source of Object.values(sources))assert.equal(sha(await readFile(source.path)),source.model.sha256)
 for(const name of ['lazy-unified-main-','lazy-native-main-','lazy-slides-main-'])assert.ok([...chunks.keys()].some(path=>path.includes(name)),name)
 const evidence={ok:true,mode:'built-browser-pptx-comments-'+mode,apiRoutesAreFixtures:true,realPythonNodeBridge:true,realZipLxmlReadback:true,inputBaseline,browserVersion:browser.version(),manifestSha256,nodeBridgeSha256,fixtureScriptSha256,sources:Object.fromEntries(Object.entries(sources).map(([k,s])=>[k,{sha256:s.model.sha256,path:s.path,readback:s.readback}])),payload,verified,boundaryEvidence,layoutEvidence,componentLayouts,requests,runtimeJavaScript:[...chunks.values()],pageErrors,consoleErrors,failedResponses,routeErrors}
 await writeFile(resolve(output,'evidence.json'),JSON.stringify(evidence,null,2));console.log(JSON.stringify({ok:true,mode:evidence.mode,output,manifestSha256,nodeBridgeSha256,javascriptCount:chunks.size,saveRequests:requests.filter(r=>r.path.endsWith('/save')).length}))
}catch(error){await page?.screenshot({path:resolve(output,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(resolve(output,'failure.json'),JSON.stringify({error:error.message,stack:error.stack,saved:!!payload,requests,pageErrors,consoleErrors,failedResponses,routeErrors},null,2));throw error}
finally{await browser?.close();await new Promise(done=>server.close(done))}
