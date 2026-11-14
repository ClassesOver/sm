// 生产静态资产和真实PPTX引擎；授权/context/保存登记为显式fixture。
import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {readFile,writeFile,mkdir,copyFile} from 'node:fs/promises'
import {createServer} from 'node:http'
import {spawnSync} from 'node:child_process'
import {dirname,resolve,extname} from 'node:path'
import {fileURLToPath} from 'node:url'
import {chromium} from 'playwright'
import {inspectSizeLayout} from './office-pptx-size-layout.mjs'
const fixtureRoot=dirname(fileURLToPath(import.meta.url)),repo=resolve(fixtureRoot,'../../../..'),staticRoot=resolve(repo,'smart_reporting/report_editor/static'),runtime=resolve(repo,'smart_reporting/reporting/slides_engine')
const output=process.env.PPTX_SIZE_OUTPUT,port=Number(process.env.PPTX_SIZE_PORT??4389),base='http://127.0.0.1:'+port,prefix='/reports/v1/editor/assets/',docId='size-pc',pathBase='/reports/v1/native/'+docId+'/'
const resumeFrom=process.env.PPTX_SIZE_RESUME_FROM
assert.ok(output,'Specify a fresh PPTX_SIZE_OUTPUT');await mkdir(output,{recursive:true})
await readFile(resolve(output,'saved-request.json')).then(()=>assert.fail('A successful save exists; preserve this evidence directory'),e=>{if(e.code!=='ENOENT')throw e})
const sha=b=>createHash('sha256').update(b).digest('hex'),manifest=sha(await readFile(resolve(staticRoot,'.vite/manifest.json'))),bridges={}
for(const name of ['edit-pptx.mjs','render-pptx.mjs'])bridges[name]=sha(await readFile(resolve(runtime,'dist',name)))
assert.equal(manifest,process.env.PPTX_EXPECTED_MANIFEST_SHA256)
const file=n=>resolve(output,'revision-'+n+'.pptx')
const engine=payload=>{const r=spawnSync(resolve(repo,'.venv/bin/python'),[resolve(fixtureRoot,'office-pptx-size-fixture.py')],{cwd:repo,env:{...process.env,PYTHONPATH:repo},input:JSON.stringify(payload),encoding:'utf8',maxBuffer:20*1024*1024,timeout:120000});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout)}
let resumeRequest,originalFailure,layout={cases:[],failures:[]}
if(resumeFrom){
 assert.notEqual(resolve(resumeFrom),resolve(output));resumeRequest=JSON.parse(await readFile(resolve(resumeFrom,'saved-request.json'),'utf8'));originalFailure=JSON.parse(await readFile(resolve(resumeFrom,'failure.json'),'utf8'));assert.equal(originalFailure.saved,true)
 layout=JSON.parse(await readFile(resolve(resumeFrom,'size-layout.json'),'utf8'));assert.equal(layout.cases.length,20);assert.deepEqual(layout.failures,[])
 for(const name of ['revision-1.pptx','revision-2.pptx','saved-request.json'])await copyFile(resolve(resumeFrom,name),resolve(output,name))
 for(const c of layout.cases)for(const name of c.screenshots)await copyFile(resolve(resumeFrom,name),resolve(output,name))
}
const revisions={1:engine(resumeFrom?{mode:'inspect',source:file(1)}:{mode:'create',output:file(1)}),...(resumeFrom?{2:engine({mode:'inspect',source:file(2)})}:{})},errors=[],checks=[],resources=new Map(),requests=[]
let browser,page,saved=false,stage='start',routeError
const server=createServer(async(req,res)=>{try{const path=new URL(req.url,base).pathname;if(path==='/favicon.ico'){res.writeHead(200,{'Content-Type':'image/svg+xml'});res.end('<svg xmlns="http://www.w3.org/2000/svg"/>');return}
 if(path==='/size-download.pptx'){assert.ok(revisions[2]);const b=await readFile(file(2));res.writeHead(200,{'Content-Type':'application/vnd.openxmlformats-officedocument.presentationml.presentation','Content-Disposition':'attachment; filename=size.pptx','Content-Length':b.length});res.end(b);return}
 assert.ok(path.startsWith(prefix));const target=resolve(staticRoot,path.slice(prefix.length));assert.ok(target.startsWith(staticRoot+'/'));const data=await readFile(target);res.writeHead(200,{'Content-Type':{'.js':'application/javascript','.css':'text/css','.html':'text/html','.woff2':'font/woff2'}[extname(target)]??'application/octet-stream'});res.end(data)
 }catch{res.writeHead(404);res.end('not found')}})
await new Promise((done,reject)=>{server.once('error',reject);server.listen(port,'127.0.0.1',done)})
try{
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})});page=await browser.newPage({viewport:{width:1600,height:1000}})
 if(resumeFrom){
  const identity={documentId:docId,revision:1,sourceSha256:revisions[1].sha256,scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'}}
  const key='native-editor-draft:v1:'+JSON.stringify(['fixture','fixture','fixture','fixture',docId,1,identity.sourceSha256])
  await page.addInitScript(({key,value})=>{if(location.pathname.endsWith('/1'))localStorage.setItem(key,JSON.stringify(value))},{key,value:{version:1,identity,operations:resumeRequest.operations,pending:{action:'save',request:resumeRequest}}})
 }
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});page.on('crash',()=>errors.push('renderer crashed'))
 page.on('response',r=>{const path=new URL(r.url()).pathname;if(r.status()>=400)errors.push(r.status()+' '+path);if(r.status()===200&&path.startsWith(prefix)&&/\.(?:js|css)$/.test(path))checks.push(r.body().then(async b=>{assert.equal(sha(b),sha(await readFile(resolve(staticRoot,path.slice(prefix.length)))));resources.set(path,{sha256:sha(b),size:b.length})}).catch(e=>errors.push(String(e))))})
 await page.route(new RegExp(pathBase+'[0-9]+$'),async route=>route.fulfill({body:await readFile(resolve(staticRoot,'native.html')),contentType:'text/html'}))
 await page.route('**'+pathBase+'*/api/**',async route=>{try{
  const request=route.request(),path=new URL(request.url()).pathname,n=Number(path.split('/')[5]),entry=revisions[n],post=request.method()==='POST'?request.postDataJSON():undefined;requests.push({path,method:request.method()})
  if(path.endsWith('/context'))return route.fulfill({json:{context:{documentId:docId,format:'pptx',revision:n,parentRevision:n>1?n-1:null,scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},sourceFile:{path:'revision-'+n+'.pptx',size:entry.size,sha256:entry.sha256,mediaType:'application/vnd.openxmlformats-officedocument.presentationml.presentation'},origin:'upload'},csrfToken:'fixture',capabilities:{pptx_editor:true},editingEnabled:true}})
  if(path.endsWith('/file'))return route.fulfill({body:await readFile(file(n)),contentType:'application/vnd.openxmlformats-officedocument.presentationml.presentation'})
  // 初始iframe回退在真实RenderTree画布就绪前短暂请求；本专项不验收PDF渲染。
  if(path.endsWith('/preview.pdf')&&request.method()==='GET')return route.fulfill({status:204,body:''})
  assert.equal(post?.expectedSha256,entry.sha256)
  if(path.endsWith('/preview')){const preview=engine({mode:'inspect',source:file(n),operations:post.operations});return route.fulfill({json:{sourceSha256:entry.sha256,draftSha256:preview.sha256,model:preview.model}})}
  if(path.endsWith('/render-tree'))return route.fulfill({json:engine({mode:'render',source:file(n),operations:post.operations})})
  assert.ok(path.endsWith('/save'));assert.equal(saved,false);assert.equal(post.operations.length,1);assert.equal(post.operations[0].kind,'editSlides');assert.deepEqual(post.operations[0].slideSize,{cx:9000000,cy:7200000})
  if(resumeFrom)assert.deepEqual(post,resumeRequest)
  else{revisions[2]=engine({mode:'patch',source:file(1),output:file(2),operations:post.operations});await writeFile(resolve(output,'saved-request.json'),JSON.stringify(post,null,2))}
  saved=true
  return route.fulfill({json:{documentId:docId,revision:2,parentRevision:1,revisionRegistered:true,pptx:{downloadUrl:base+'/size-download.pptx'},artifacts:{pptx:{downloadUrl:base+'/size-download.pptx',size:revisions[2].size,sha256:revisions[2].sha256}},editor:{openUrl:pathBase+'2'},validation:{ok:false,issues:[{code:'fixture_review_pending',message:'幻灯片尺寸版式待复核，文件已生成。'}]}}})
 }catch(error){routeError=error;await route.fulfill({status:500,json:{detail:String(error)}})}})
 const open=async n=>{await page.goto(base+pathBase+n);await page.locator('.slides-canvas canvas').first().waitFor({timeout:60000})}
 const draft=()=>page.evaluate(()=>Object.entries(localStorage).filter(([k])=>k.startsWith('native-editor-draft:')).map(([k,v])=>[k,JSON.parse(v).operations]))
 const operations=async()=>(await draft()).flatMap(([,ops])=>ops)
 const waitOps=count=>page.waitForFunction(count=>Object.entries(localStorage).filter(([k])=>k.startsWith('native-editor-draft:')).flatMap(([,v])=>JSON.parse(v).operations).length===count,count)
 const dialog=page.getByRole('dialog',{name:'自定义幻灯片尺寸',exact:true}),opener=page.locator('[data-command=customSlideSize]'),openDialog=async()=>{await page.locator('[data-ribbon-tab=design]').click();await opener.click();await dialog.waitFor()}
 const width=dialog.getByLabel('幻灯片宽度',{exact:true}),height=dialog.getByLabel('幻灯片高度',{exact:true}),unit=dialog.getByLabel('尺寸单位',{exact:true}),apply=dialog.locator('[data-command=applyCustomSlideSize]')
 if(!resumeFrom){await open(1);await openDialog();assert.equal(await width.evaluate(n=>n===document.activeElement),true)
 for(const value of ['in','mm','cm'])await unit.selectOption(value)
 assert.equal(await width.inputValue(),'25.4');assert.equal(await height.inputValue(),'19.05');assert.deepEqual(await operations(),[])
 stage='initial-layout';await inspectSizeLayout(page,{output,phase:'initial',layout,draft})}
 if(process.env.PPTX_SIZE_BASELINE==='1'){await Promise.all(checks);assert.deepEqual(errors,[]);assert.equal(saved,false);await writeFile(resolve(output,'baseline.json'),JSON.stringify({manifest,layout,saved,errors},null,2));console.log(JSON.stringify({baseline:true,failures:layout.failures.length}));}
 else{
 let applied
 if(!resumeFrom){
 assert.deepEqual(layout.failures,[]);await dialog.locator('[data-command=cancelCustomSlideSize]').click();assert.equal(await opener.evaluate(n=>n===document.activeElement),true);assert.deepEqual(await operations(),[])
 await openDialog();await width.fill('0');await apply.click();assert.match(await dialog.locator('[role=alert]').innerText(),/1–56/);await unit.selectOption('in');assert.equal(await unit.inputValue(),'cm');assert.equal(await width.inputValue(),'0');assert.deepEqual(await operations(),[])
 stage='error-layout';await inspectSizeLayout(page,{output,phase:'error',layout,draft});assert.deepEqual(layout.failures,[]);await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});assert.equal(await opener.evaluate(n=>n===document.activeElement),true)
 await openDialog();assert.equal(await width.inputValue(),'25.4');await dialog.getByRole('button',{name:'关闭自定义幻灯片尺寸',exact:true}).click();assert.deepEqual(await operations(),[])
 await openDialog();await width.fill('25');await height.fill('20');for(const value of ['in','mm','cm'])await unit.selectOption(value);assert.equal(await width.inputValue(),'25');assert.equal(await height.inputValue(),'20');await apply.click();await waitOps(1);applied=await operations();assert.deepEqual(applied[0].slideSize,{cx:9000000,cy:7200000})
 await page.locator('[data-source-action=onUndo]').click();await waitOps(0);await page.locator('[data-source-action=onRedo]').click();await waitOps(1);assert.deepEqual(await operations(),applied);await page.reload();await page.locator('.slides-canvas canvas').first().waitFor();await waitOps(1);assert.deepEqual(await operations(),applied)
 await openDialog();assert.equal(await width.inputValue(),'25');assert.equal(await height.inputValue(),'20');stage='recovered-layout';await inspectSizeLayout(page,{output,phase:'recovered',layout,draft});assert.deepEqual(layout.failures,[]);await dialog.locator('[data-command=cancelCustomSlideSize]').click()
 }else{await open(1);await waitOps(1);applied=await operations();assert.deepEqual(applied,resumeRequest.operations)}
 stage='save';await page.locator('[data-action=save]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存，存在告警',null,{timeout:120000});if(routeError)throw routeError
 await page.getByText('幻灯片尺寸版式待复核，文件已生成。',{exact:false}).waitFor();const downloading=page.waitForEvent('download');await page.getByRole('link',{name:'下载 PPTX',exact:true}).click();const download=await downloading;assert.equal(await download.failure(),null);await download.saveAs(resolve(output,'downloaded.pptx'));assert.equal(sha(await readFile(resolve(output,'downloaded.pptx'))),revisions[2].sha256)
 stage='reopen';await open(2);await openDialog();assert.equal(await width.inputValue(),'25');assert.equal(await height.inputValue(),'20');await inspectSizeLayout(page,{output,phase:resumeFrom?'replayed':'reopened',layout,draft});assert.deepEqual(layout.failures,[]);await dialog.getByRole('button',{name:'关闭自定义幻灯片尺寸',exact:true}).click();await page.locator('.canvas-status').filter({hasText:'点击对象选择，拖动调整位置，拖动角点缩放'}).waitFor({timeout:60000});await page.screenshot({path:resolve(output,'reopened-file.png'),fullPage:true})
 await Promise.all(checks);assert.deepEqual(errors,[]);assert.equal(sha(await readFile(resolve(staticRoot,'.vite/manifest.json'))),manifest);for(const[name,hash]of Object.entries(bridges))assert.equal(sha(await readFile(resolve(runtime,'dist',name))),hash)
 await writeFile(resolve(output,'evidence.json'),JSON.stringify({ok:true,routeIsFixture:true,previewPdfFallbackSuppressed:true,realPythonSave:!resumeFrom,...(resumeFrom?{responseReplay:true,originalActualSaveDirectory:resumeFrom,originalFailure}:{}),actualBrowserDownload:true,manifest,bridges,sourceSha256:revisions[1].sha256,outputSha256:revisions[2].sha256,layout,applied,requests,resources:Object.fromEntries(resources),errors},null,2));console.log(JSON.stringify({ok:true,output,cases:layout.cases.length,resources:resources.size}))
 }
}catch(error){await page?.screenshot({path:resolve(output,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(resolve(output,'failure.json'),JSON.stringify({stage,saved,error:String(error),stack:error.stack,errors,routeError:String(routeError??'')},null,2));throw error}
finally{await browser?.close();await new Promise(done=>server.close(done))}
