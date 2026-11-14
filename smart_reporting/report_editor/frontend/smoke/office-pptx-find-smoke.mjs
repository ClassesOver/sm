// 冻结生产资产、真实PPTX引擎与HTTP附件；授权/context/CSRF/修订登记为显式fixture。
import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {readFile,writeFile,mkdir,access} from 'node:fs/promises'
import {createServer} from 'node:http'
import {spawnSync} from 'node:child_process'
import {join,resolve,extname} from 'node:path'
import {fileURLToPath} from 'node:url'
import {isDeepStrictEqual} from 'node:util'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
import {inspectFindLayout} from './office-pptx-find-layout.mjs'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=resolve(frontend,'../../..'),staticRoot=resolve(frontend,'../static'),runtime=resolve(repo,'smart_reporting/reporting/slides_engine')
const output=process.env.PPTX_FIND_OUTPUT,port=Number(process.env.PPTX_FIND_PORT??4394),base='http://127.0.0.1:'+port,prefix='/reports/v1/editor/assets/',pathBase='/reports/v1/native/find-pc/'
assert.ok(output,'PPTX_FIND_OUTPUT must be a fresh directory');await mkdir(output,{recursive:true})
let exists=false;try{await access(join(output,'saved-request.json'));exists=true}catch{}assert.equal(exists,false,'never repeat an existing save')
const sha=b=>createHash('sha256').update(b).digest('hex'),manifest=await readFile(join(staticRoot,'.vite/manifest.json')),bridges={}
assert.equal(sha(manifest),process.env.PPTX_EXPECTED_MANIFEST_SHA256);await writeFile(join(output,'build-manifest.json'),manifest)
for(const name of ['edit-pptx.mjs','render-pptx.mjs'])bridges[name]=sha(await readFile(join(runtime,'dist',name)))
const file=n=>join(output,'revision-'+n+'.pptx')
const engine=payload=>{const r=spawnSync(join(repo,'.venv/bin/python'),[join(frontend,'smoke/office-pptx-find-fixture.py')],{cwd:repo,env:{...process.env,PYTHONPATH:repo},input:JSON.stringify(payload),encoding:'utf8',maxBuffer:20*1024*1024,timeout:120000});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout)}
const revisions={1:engine({mode:'create',output:file(1)})},layout={cases:[],failures:[]},errors=[],requests=[],checks=[],resources=new Map()
const safe=revisions[1].model.slides.flatMap(s=>s.elements.filter(e=>e.findReplaceEditable&&e.text.includes('收入')).map(e=>({slideIndex:s.slideIndex,id:e.id,name:e.name,text:e.text})))
assert.equal(safe.length,3);assert.equal(safe.reduce((n,e)=>n+(e.text.match(/收入/g)||[]).length,0),4)
let browser,page,saved=false,stage='start',routeError
const media='application/vnd.openxmlformats-officedocument.presentationml.presentation'
const server=createServer(async(req,res)=>{try{const path=new URL(req.url,base).pathname
 if(path==='/favicon.ico'){res.writeHead(200,{'Content-Type':'image/svg+xml'});res.end('<svg xmlns="http://www.w3.org/2000/svg"/>');return}
 if(path==='/find-download.pptx'){const data=await readFile(file(2));res.writeHead(200,{'Content-Type':media,'Content-Disposition':'attachment; filename=find.pptx','Content-Length':data.length});res.end(data);requests.push({method:req.method,path:'download-http'});return}
 assert.ok(path.startsWith(prefix));const target=resolve(staticRoot,path.slice(prefix.length));assert.ok(target.startsWith(staticRoot+'/'));const data=await readFile(target);res.writeHead(200,{'Content-Type':{'.js':'application/javascript','.css':'text/css','.html':'text/html','.woff2':'font/woff2'}[extname(target)]??'application/octet-stream'});res.end(data)
 }catch{res.writeHead(404);res.end('not found')}})
await new Promise((done,reject)=>{server.once('error',reject);server.listen(port,'127.0.0.1',done)})
try{
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})});page=await browser.newPage({viewport:{width:1440,height:900}})
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});page.on('crash',()=>errors.push('renderer crashed'))
 page.on('response',r=>{const path=new URL(r.url()).pathname;if(r.status()>=400)errors.push(r.status()+' '+path);if(r.status()===200&&path.startsWith(prefix)&&/\.(?:js|css)$/.test(path))checks.push(r.body().then(async b=>{assert.equal(sha(b),sha(await readFile(join(staticRoot,path.slice(prefix.length)))));resources.set(path,{sha256:sha(b),size:b.length})}).catch(e=>errors.push(String(e))))})
 await page.route(new RegExp(pathBase+'[0-9]+$'),async route=>route.fulfill({body:await readFile(join(staticRoot,'native.html')),contentType:'text/html'}))
 await page.route('**'+pathBase+'*/api/**',async route=>{try{
  const request=route.request(),path=new URL(request.url()).pathname,n=Number(path.split('/')[5]),entry=revisions[n],post=request.method()==='POST'?request.postDataJSON():undefined;requests.push({path,method:request.method()})
  if(path.endsWith('/context'))return route.fulfill({json:{context:{documentId:'find-pc',format:'pptx',revision:n,parentRevision:n>1?n-1:null,scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},sourceFile:{path:'revision-'+n+'.pptx',size:entry.size,sha256:entry.sha256,mediaType:media},origin:'upload'},csrfToken:'fixture',capabilities:{pptx_editor:true},editingEnabled:true}})
  if(path.endsWith('/file'))return route.fulfill({body:await readFile(file(n)),contentType:media})
  if(path.endsWith('/preview.pdf')&&request.method()==='GET')return route.fulfill({status:204,body:''})
  assert.equal(post.expectedSha256,entry.sha256)
  if(path.endsWith('/preview')){const preview=engine({mode:'inspect',source:file(n),operations:post.operations});return route.fulfill({json:{sourceSha256:entry.sha256,draftSha256:preview.sha256,model:preview.model}})}
  if(path.endsWith('/render-tree'))return route.fulfill({json:engine({mode:'render',source:file(n),operations:post.operations})})
  assert.ok(path.endsWith('/save'));assert.equal(saved,false);assert.equal(post.operations.length,1);assert.equal(post.operations[0].kind,'editSlides');assert.equal(post.operations[0].edits.length,3)
  revisions[2]=engine({mode:'patch',source:file(1),output:file(2),operations:post.operations});saved=true;await writeFile(join(output,'saved-request.json'),JSON.stringify(post,null,2))
  return route.fulfill({json:{documentId:'find-pc',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{pptx:{downloadUrl:base+'/find-download.pptx',size:revisions[2].size,sha256:revisions[2].sha256}},editor:{openUrl:pathBase+'2'},validation:{ok:false,issues:[{code:'fixture_review_pending',message:'查找替换版式待复核，文件已生成。'}]}}})
 }catch(error){routeError=error;await route.fulfill({status:500,json:{detail:String(error)}})}})
 const open=async n=>{await page.goto(base+pathBase+n);await page.locator('.slides-canvas canvas').first().waitFor({timeout:60000})}
 const draft=()=>page.evaluate(()=>Object.entries(localStorage).filter(([k])=>k.startsWith('native-editor-draft:')).map(([k,v])=>[k,JSON.parse(v).operations]))
 const operations=async()=>(await draft()).flatMap(([,ops])=>ops)
 const waitOperations=async expected=>{for(let i=0;i<150;i++){const current=await operations();if(isDeepStrictEqual(current,expected))return;await delay(100)}assert.deepEqual(await operations(),expected)}
 const dialog=page.getByRole('dialog',{name:'查找和替换',exact:true}),opener=page.locator('[data-command=findReplace]'),openDialog=async()=>{await page.locator('[data-ribbon-tab=home]').click();await opener.click();await dialog.waitFor()}
 const query=dialog.getByLabel('查找文字',{exact:true}),replacement=dialog.getByLabel('替换为',{exact:true}),result=dialog.locator('[role=status]'),click=command=>dialog.locator(`[data-command=${command}]`).click()
 await open(1);await openDialog();assert.equal(await query.evaluate(n=>n===document.activeElement),true);await inspectFindLayout(page,{output,phase:'initial',layout,draft})
 if(process.env.PPTX_FIND_BASELINE==='1'){assert.equal(saved,false);await Promise.all(checks);assert.deepEqual(errors,[]);await writeFile(join(output,'baseline.json'),JSON.stringify({manifest:sha(manifest),layout,saved,errors},null,2));console.log(JSON.stringify({baseline:true,cases:layout.cases.length,failures:layout.failures.length}))}
 else{
  assert.deepEqual(layout.failures,[]);stage='find';await click('findNext');assert.match(await result.innerText(),/未找到/);await query.fill('不存在的文字');await query.press('Enter');assert.match(await result.innerText(),/未找到/)
  await query.fill('Revenue');await query.press('Enter');assert.match(await result.innerText(),/共 3 处匹配/);await dialog.getByLabel('区分大小写',{exact:true}).check();await query.press('Enter');assert.match(await result.innerText(),/共 2 处匹配/);await dialog.getByLabel('区分大小写',{exact:true}).uncheck();assert.deepEqual(await operations(),[])
  await query.fill('收入');await query.press('Enter');assert.match(await result.innerText(),/共 4 处匹配/);await dialog.getByRole('button',{name:'关闭查找和替换',exact:true}).click();assert.equal(await opener.evaluate(n=>n===document.activeElement),true)
  await openDialog();stage='error';await query.fill('收入');await replacement.fill('超'.repeat(20001));await click('replaceAll');assert.match(await result.innerText(),/20000/);assert.deepEqual(await operations(),[]);await inspectFindLayout(page,{output,phase:'error',layout,draft});assert.deepEqual(layout.failures,[]);await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});assert.equal(await opener.evaluate(n=>n===document.activeElement),true)
  await openDialog();await query.fill('收入');await replacement.fill('营收 $& <PC> 😀');await click('replace');assert.deepEqual(await operations(),[]);await click('replace');assert.match(await result.innerText(),/已替换 1 处/);const single=await operations();assert.equal(single[0].edits.length,1);assert.equal(single[0].edits[0].text,'营收 $& <PC> 😀 收入 & <保真> 😀');await click('closeFindReplace');await page.locator('[data-source-action=onUndo]').click();await waitOperations([])
  await openDialog();await query.fill('收入');await replacement.fill('营收 $& <PC> 😀');await click('replaceAll');assert.match(await result.innerText(),/已替换 4 处/);const applied=await operations();assert.equal(applied[0].edits.length,3);stage='applied';await inspectFindLayout(page,{output,phase:'applied',layout,draft});assert.deepEqual(layout.failures,[]);await click('closeFindReplace');assert.equal(await opener.evaluate(n=>n===document.activeElement),true)
  await page.locator('[data-source-action=onUndo]').click();await waitOperations([]);await page.locator('[data-source-action=onRedo]').click();await waitOperations(applied);await page.reload();await page.locator('.slides-canvas canvas').first().waitFor();await waitOperations(applied)
  stage='save';await page.locator('[data-action=save]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存，存在告警',null,{timeout:120000});if(routeError)throw routeError
  await page.getByText('查找替换版式待复核，文件已生成。',{exact:false}).waitFor();const downloading=page.waitForEvent('download');await page.getByRole('link',{name:'下载 PPTX',exact:true}).click();const download=await downloading;assert.equal(await download.failure(),null);await download.saveAs(join(output,'downloaded.pptx'));assert.deepEqual(await readFile(file(2)),await readFile(join(output,'downloaded.pptx')));assert.equal(sha(await readFile(join(output,'downloaded.pptx'))),revisions[2].sha256)
  const independent=engine({mode:'verify',directory:output})
  stage='reopen';await open(2);await openDialog();await query.fill('营收 $& <PC> 😀');await query.press('Enter');assert.match(await result.innerText(),/共 4 处匹配/);await inspectFindLayout(page,{output,phase:'reopened',layout,draft});assert.deepEqual(layout.failures,[]);await click('closeFindReplace');await page.screenshot({path:join(output,'reopened-file.png'),fullPage:true})
  await Promise.all(checks);assert.deepEqual(errors,[]);assert.deepEqual(await readFile(join(staticRoot,'.vite/manifest.json')),manifest);for(const [name,hash]of Object.entries(bridges))assert.equal(sha(await readFile(join(runtime,'dist',name))),hash)
  await writeFile(join(output,'evidence.json'),JSON.stringify({ok:true,routeIsFixture:true,previewPdfFallbackSuppressed:true,realPythonSave:true,actualBrowserDownload:true,savedRevisions:1,manifest:sha(manifest),bridges,layout,applied,independent,requests,resources:Object.fromEntries(resources),errors},null,2));console.log(JSON.stringify({ok:true,cases:layout.cases.length,resources:resources.size,output}))
 }
}catch(error){await page?.screenshot({path:join(output,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(join(output,'failure.json'),JSON.stringify({stage,saved,error:String(error),stack:error.stack,errors,routeError:String(routeError??'')},null,2));throw error}
finally{await browser?.close();await new Promise(done=>server.close(done))}
