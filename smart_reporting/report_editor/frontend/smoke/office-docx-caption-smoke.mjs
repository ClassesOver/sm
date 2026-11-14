// 生产静态资产、真实Word引擎与浏览器下载；授权/context/修订登记为显式fixture。
import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {readFile,writeFile,mkdir} from 'node:fs/promises'
import {createServer} from 'node:http'
import {spawnSync} from 'node:child_process'
import {dirname,resolve,extname} from 'node:path'
import {fileURLToPath} from 'node:url'
import {chromium} from 'playwright'
import {inspectCaptionLayout} from './office-docx-caption-layout.mjs'
import {inspectDocxBodyViewport} from './docx-shortscreen-check.mjs'
const fixtureRoot=dirname(fileURLToPath(import.meta.url)),repo=resolve(fixtureRoot,'../../../..'),staticRoot=resolve(process.env.DOCX_STATIC_ROOT??resolve(repo,'smart_reporting/report_editor/static')),runtime=resolve(repo,'smart_reporting/reporting/doc_engine')
const output=process.env.DOCX_CAPTION_OUTPUT,port=Number(process.env.DOCX_CAPTION_PORT??4388),base='http://127.0.0.1:'+port,prefix='/reports/v1/editor/assets/',docId='caption-pc',pathBase='/reports/v1/native/'+docId+'/'
assert.ok(output,'Specify a fresh DOCX_CAPTION_OUTPUT');await mkdir(output,{recursive:true})
await readFile(resolve(output,'saved-request.json')).then(()=>assert.fail('A successful save exists; preserve this evidence directory'),e=>{if(e.code!=='ENOENT')throw e})
const sha=b=>createHash('sha256').update(b).digest('hex'),manifest=sha(await readFile(resolve(staticRoot,'.vite/manifest.json'))),bridge=sha(await readFile(resolve(runtime,'dist/edit-docx.mjs')))
assert.equal(manifest,process.env.DOCX_EXPECTED_MANIFEST_SHA256)
const file=n=>resolve(output,'revision-'+n+'.docx'),bytes=entry=>Buffer.from(entry.bytes,'base64')
const engine=payload=>{const r=spawnSync(resolve(repo,'.venv/bin/python'),[resolve(fixtureRoot,'native-word-toc-thread-fixture.py')],{cwd:repo,env:{...process.env,PYTHONPATH:repo,AGENT_REPORTING_DOC_ENGINE_DIR:runtime},input:JSON.stringify(payload),encoding:'utf8',maxBuffer:20*1024*1024,timeout:120000});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout)}
const revisions={1:engine({mode:'create',case:'toc',output:file(1)})},sourceSha256=revisions[1].model.sourceSha256,errors=[],checks=[],resources=new Map(),layout={cases:[],failures:[]},requests=[]
let browser,page,saved=false,stage='start',routeError
const caretStates=[]
const server=createServer(async(req,res)=>{try{const path=new URL(req.url,base).pathname;if(path==='/favicon.ico'){res.writeHead(200,{'Content-Type':'image/svg+xml'});res.end('<svg xmlns="http://www.w3.org/2000/svg"/>');return}
 if(path==='/caption-download.docx'){assert.ok(revisions[2]);const b=bytes(revisions[2]);res.writeHead(200,{'Content-Type':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','Content-Disposition':'attachment; filename=caption.docx','Content-Length':b.length});res.end(b);return}
 assert.ok(path.startsWith(prefix));const target=resolve(staticRoot,path.slice(prefix.length));assert.ok(target.startsWith(staticRoot+'/'));const data=await readFile(target);res.writeHead(200,{'Content-Type':{'.js':'application/javascript','.css':'text/css','.html':'text/html','.woff2':'font/woff2'}[extname(target)]??'application/octet-stream'});res.end(data)
 }catch{res.writeHead(404);res.end('not found')}})
await new Promise((done,reject)=>{server.once('error',reject);server.listen(port,'127.0.0.1',done)})
try{
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})});page=await browser.newPage({viewport:{width:1600,height:1000}})
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});page.on('crash',()=>errors.push('renderer crashed'))
 page.on('response',r=>{const path=new URL(r.url()).pathname;if(r.status()>=400)errors.push(r.status()+' '+path);if(r.status()===200&&path.startsWith(prefix)&&/\.(?:js|css)$/.test(path))checks.push(r.body().then(async b=>{assert.equal(sha(b),sha(await readFile(resolve(staticRoot,path.slice(prefix.length)))));resources.set(path,{sha256:sha(b),size:b.length})}).catch(e=>errors.push(String(e))))})
 await page.route(new RegExp(pathBase+'[0-9]+$'),async route=>route.fulfill({body:await readFile(resolve(staticRoot,'native.html')),contentType:'text/html'}))
 await page.route('**'+pathBase+'*/api/**',async route=>{try{
  const request=route.request(),path=new URL(request.url()).pathname,n=Number(path.split('/')[5]),entry=revisions[n],post=request.method()==='POST'?request.postDataJSON():undefined;requests.push({path,method:request.method()})
  if(path.endsWith('/context'))return route.fulfill({json:{context:{documentId:docId,format:'docx',revision:n,parentRevision:n>1?n-1:null,scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},sourceFile:{path:'revision-'+n+'.docx',size:bytes(entry).length,sha256:entry.model.sourceSha256,mediaType:'application/vnd.openxmlformats-officedocument.wordprocessingml.document'},origin:'upload'},csrfToken:'fixture',capabilities:{docx_editor:true},editingEnabled:true}})
  if(path.endsWith('/file'))return route.fulfill({body:bytes(entry),contentType:'application/vnd.openxmlformats-officedocument.wordprocessingml.document'})
  assert.equal(post?.expectedSha256,entry.model.sourceSha256)
  if(path.endsWith('/preview')){assert.deepEqual(post.operations,[]);return route.fulfill({json:{sourceSha256:entry.model.sourceSha256,draftSha256:entry.model.sourceSha256,model:entry.model}})}
  assert.ok(path.endsWith('/save'));assert.equal(saved,false);assert.equal(post.operations.length,1);assert.equal(post.operations[0].kind,'insertCaption')
  revisions[2]=engine({mode:'patch',source:file(1),output:file(2),operations:post.operations});saved=true;await writeFile(resolve(output,'saved-request.json'),JSON.stringify(post,null,2))
  return route.fulfill({json:{documentId:docId,revision:2,parentRevision:1,revisionRegistered:true,artifacts:{word:{downloadUrl:base+'/caption-download.docx',size:bytes(revisions[2]).length,sha256:revisions[2].model.sourceSha256}},editor:{openUrl:pathBase+'2'},validation:{ok:false,issues:[{code:'fixture_review_pending',message:'题注版式验收待复核，文件已生成。'}]}}})
 }catch(error){routeError=error;await route.fulfill({status:500,json:{detail:String(error)}})}})
 const open=async n=>{await page.goto(base+pathBase+n);await page.locator('.docx-source-home').waitFor({timeout:60000})}
 const draft=()=>page.evaluate(()=>Object.entries(localStorage).filter(([k])=>k.startsWith('native-editor-draft:')).map(([k,v])=>[k,JSON.parse(v).operations]))
 const operations=async()=>(await draft()).flatMap(([,ops])=>ops)
 const waitOps=count=>page.waitForFunction(count=>Object.entries(localStorage).filter(([k])=>k.startsWith('native-editor-draft:')).flatMap(([,v])=>JSON.parse(v).operations).length===count,count)
 const caret=async middle=>{
  const editor=page.locator('.tiptap'),selection=()=>editor.evaluate(node=>{const s=node.editor.state.selection;return{from:s.from,to:s.to,depth:s.$from.depth,offset:s.$from.parentOffset,parent:s.$from.parent.textContent}})
  await editor.getByText('目录前言',{exact:true}).click();await page.keyboard.press('Home');const home=await selection()
  await page.keyboard.press('Control+Home')
  const waitOffset=offset=>page.waitForFunction(offset=>{const s=document.querySelector('.tiptap').editor.state.selection;return s.empty&&s.$from.depth===1&&s.$from.parentOffset===offset&&s.$from.parent.textContent==='目录前言'},offset)
  await waitOffset(0);const start=await selection();assert.equal(start.depth,1);assert.equal(start.offset,0);assert.equal(start.parent,'目录前言');assert.equal(start.from,start.to)
  if(middle){await page.keyboard.press('ArrowRight');await waitOffset(1)}
  caretStates.push({viewport:page.viewportSize(),middle,home,start,final:await selection()})
  await writeFile(resolve(output,'caret-states.json'),JSON.stringify(caretStates,null,2))
 }
 const dialog=page.getByRole('dialog',{name:'插入题注',exact:true}),openDialog=async()=>{await page.locator('[data-tab-id=references]').click();await page.locator('[data-action=caption-insert]').click();await dialog.waitFor()}
 await open(1)
 stage='dynamic-selection-focus';const dynamicFocus=[]
 for(const [width,height] of [[1440,900],[320,640],[640,360],[390,320]]){
  await page.setViewportSize({width,height});await page.locator('[data-tab-id=references]').click()
  const shortscreen=process.env.DOCX_VERIFY_SHORTSCREEN==='1'?await inspectDocxBodyViewport(page):undefined
  await caret(false);await openDialog()
  const before=await draft(),input=dialog.locator('[data-caption-text]'),confirm=dialog.locator('[data-caption-confirm]'),status=dialog.getByRole('status',{name:'题注状态'})
  await input.fill('未提交题注 & <保真>');assert.equal(await confirm.isEnabled(),true);await confirm.focus()
  // Tiptap 将真实 Editor 挂载在它的 DOM 上；派发真实选区事务，模拟窗口打开后的来源变化。
  await page.locator('.tiptap').evaluate(node=>{const editor=node.editor;if(!editor)throw Error('Tiptap Editor unavailable');editor.commands.setTextSelection(editor.state.selection.from===1?2:1)})
  assert.equal(await confirm.isDisabled(),true);assert.equal(await status.evaluate(node=>document.activeElement===node),true)
  await page.keyboard.press('Tab');assert.equal(await dialog.evaluate(node=>node.contains(document.activeElement)),true)
  await input.focus();await input.fill('保留描述');assert.equal(await input.evaluate(node=>document.activeElement===node),true)
  await status.focus();assert.equal(await status.evaluate(node=>{const r=node.getBoundingClientRect();return node.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}),true)
  await page.screenshot({path:resolve(output,`caption-dynamic-${width}x${height}.png`)})
  await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});assert.equal(await page.locator('[data-action=caption-insert]').evaluate(node=>document.activeElement===node),true)
  assert.deepEqual(await draft(),before);dynamicFocus.push({width,height,source:'real Tiptap selection transaction',statusFocused:true,tabContained:true,inputPreserved:true,draftUnchanged:true,shortscreen})
 }
 await writeFile(resolve(output,'dynamic-focus.json'),JSON.stringify(dynamicFocus,null,2))
 await page.setViewportSize({width:1600,height:1000});await caret(false);await openDialog();stage='long-layout';const text='长题注 & <😀>'.repeat(75);await dialog.locator('[data-caption-text]').fill(text)
 for(const label of ['图','表','公式']){await dialog.locator('[data-caption-label]').selectOption(label);assert.equal(await dialog.locator('[data-caption-preview]').textContent(),label+' 1 '+text)}
 await inspectCaptionLayout(page,{output,phase:'long',layout,draft})
 if(process.env.DOCX_CAPTION_BASELINE==='1'){await Promise.all(checks);assert.deepEqual(errors,[]);assert.equal(saved,false);await writeFile(resolve(output,'baseline.json'),JSON.stringify({manifest,layout,saved,errors},null,2));console.log(JSON.stringify({baseline:true,failures:layout.failures.length}));}
 else{
 assert.deepEqual(layout.failures,[]);await dialog.locator('[data-caption-cancel]').click();assert.deepEqual(await operations(),[]);assert.equal(await page.locator('[data-action=caption-insert]').evaluate(n=>n===document.activeElement),true)
 stage='blocked-layout';await caret(true);await openDialog();assert.equal(await dialog.locator('[data-caption-confirm]').isDisabled(),true);assert.match(await dialog.locator('[role=status]').innerText(),/开头或结尾/)
 await inspectCaptionLayout(page,{output,phase:'blocked',layout,draft});assert.deepEqual(layout.failures,[]);assert.deepEqual(await operations(),[]);await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'})
 stage='reopened-layout';await caret(false);await openDialog();assert.equal(await dialog.locator('[data-caption-text]').inputValue(),'');assert.equal(await dialog.locator('[data-caption-label]').inputValue(),'公式');await inspectCaptionLayout(page,{output,phase:'reopened',layout,draft});assert.deepEqual(layout.failures,[])
 await dialog.getByRole('button',{name:'关闭题注',exact:true}).click();assert.deepEqual(await operations(),[]);await openDialog();await dialog.locator('[data-caption-label]').selectOption('图');await dialog.locator('[data-caption-text]').fill('收入 & <保真> 😀');await dialog.locator('[data-caption-confirm]').click();await page.locator('.tiptap').getByText('图 1 收入 & <保真> 😀',{exact:true}).waitFor();await waitOps(1);const applied=await operations()
 await page.locator('.tiptap').focus();await page.keyboard.press('Control+z');await waitOps(0);await page.keyboard.press('Control+y');await waitOps(1);assert.deepEqual(await operations(),applied);await page.reload();await page.locator('.docx-source-home').waitFor();await waitOps(1);assert.deepEqual(await operations(),applied)
 stage='save';await page.locator('[data-action=save]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent.includes('已保存修订 2'),null,{timeout:120000});if(routeError)throw routeError
 assert.match(await page.locator('.native-delivery').innerText(),/题注版式验收待复核/);const downloading=page.waitForEvent('download');await page.getByRole('link',{name:'下载 Word',exact:true}).click();const download=await downloading;assert.equal(await download.failure(),null);await download.saveAs(resolve(output,'downloaded.docx'));assert.equal(sha(await readFile(resolve(output,'downloaded.docx'))),revisions[2].model.sourceSha256)
 stage='reopen';await open(2);await page.locator('.tiptap').getByText('图 1 收入 & <保真> 😀',{exact:true}).waitFor();await page.screenshot({path:resolve(output,'reopened-file.png'),fullPage:true})
 await page.waitForLoadState('networkidle');await Promise.all(checks);assert.deepEqual(errors,[]);assert.equal(sha(await readFile(resolve(staticRoot,'.vite/manifest.json'))),manifest);assert.equal(sha(await readFile(resolve(runtime,'dist/edit-docx.mjs'))),bridge)
 await writeFile(resolve(output,'evidence.json'),JSON.stringify({ok:true,routeIsFixture:true,realPythonSave:true,actualBrowserDownload:true,manifest,bridge,sourceSha256,outputSha256:revisions[2].model.sourceSha256,dynamicFocus,layout,applied,facts:revisions[2].facts,requests,resources:Object.fromEntries(resources),errors},null,2));console.log(JSON.stringify({ok:true,output,cases:layout.cases.length,resources:resources.size}))
 }
}catch(error){await page?.screenshot({path:resolve(output,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(resolve(output,'failure.json'),JSON.stringify({stage,saved,error:String(error),stack:error.stack,errors,routeError:String(routeError??'')},null,2));throw error}
finally{await browser?.close();await new Promise(done=>server.close(done))}
