// 当前生产构建+真实Python/Node桥；API路由fixture不代表生产鉴权，真实鉴权由独立HTTP专项覆盖。
import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {readFile,writeFile,mkdir} from 'node:fs/promises'
import {createServer} from 'node:http'
import {spawnSync} from 'node:child_process'
import {dirname,resolve,extname} from 'node:path'
import {fileURLToPath} from 'node:url'
import {chromium} from 'playwright'
const frontend=resolve(dirname(fileURLToPath(import.meta.url)),'..'),repo=resolve(frontend,'../../..'),staticRoot=resolve(frontend,'../static')
const entryOnly=process.env.DOCX_COMMENT_CREATE_ENTRY_ONLY==='1'
const output=process.env.DOCX_COMMENT_CREATE_EVIDENCE??'/tmp/word-comment-create-browser-20261111',port=Number(process.env.DOCX_COMMENT_CREATE_PORT??4308)
const sha=b=>createHash('sha256').update(b).digest('hex'),manifestSha256=sha(await readFile(resolve(staticRoot,'.vite/manifest.json')))
assert.equal(manifestSha256,process.env.DOCX_EXPECTED_MANIFEST_SHA256);await mkdir(output,{recursive:true})
const runtime=resolve(repo,'smart_reporting/reporting/doc_engine'),nodeBridgeSha256=sha(await readFile(resolve(runtime,'dist/edit-docx.mjs')))
const python=[
 'import base64,json,sys',
 'from pathlib import Path',
 'from io import BytesIO',
 'from zipfile import ZipFile',
 'from lxml import etree as E',
 'from smart_reporting.reporting.delivery.docx_native import inspect_docx,patch_docx',
 'from smart_reporting.reporting.tests.test_docx_comment_text_host import source',
 "p=json.load(sys.stdin);W='http://schemas.openxmlformats.org/wordprocessingml/2006/main';ns={'w':W}",
 "if p['mode']=='create':",
 " data=source();Path(p['path']).write_bytes(data);print(json.dumps({'bytes':base64.b64encode(data).decode(),'model':inspect_docx(data)}))",
 "elif p['mode']=='patch':",
 " data=patch_docx(Path(p['source']).read_bytes(),p['operations']);Path(p['output']).write_bytes(data);print(json.dumps({'bytes':base64.b64encode(data).decode(),'model':inspect_docx(data)}))",
 "elif p['mode']=='stale':",
 " try:patch_docx(Path(p['source']).read_bytes(),p['operations'])",
 " except ValueError as e:print(json.dumps({'rejected':True,'reason':str(e)}))",
 " else:raise AssertionError('stale target accepted')",
 'else:',
 " data=base64.b64decode(p['bytes'])",
 " with ZipFile(p['source']) as a,ZipFile(BytesIO(data)) as b:",
 "  assert b.testzip() is None;assert a.namelist()==b.namelist();changed=[n for n in a.namelist() if a.read(n)!=b.read(n)];assert changed==['word/document.xml','word/comments.xml'],changed",
 '  for n in b.namelist():',
 "   if n.endswith(('.xml','.rels')):E.fromstring(b.read(n))",
 "  comments=E.fromstring(b.read('word/comments.xml')).findall('w:comment',ns);assert len(comments)==3;assert ''.join(comments[0].itertext())=='Original note'",
 "  assert [''.join(c.itertext()) for c in comments[1:]]==p['expected'];ids=[c.get('{'+W+'}id') for c in comments];assert len(ids)==len(set(ids))",
 "  paragraph=E.fromstring(b.read('word/document.xml')).find('.//w:body/w:p',ns);selected={}",
 '  for id in ids[1:]:',
 "   active=False;text=''",
 '   for n in paragraph:',
 "    if n.tag=='{'+W+'}commentRangeStart' and n.get('{'+W+'}id')==id:active=True",
 "    elif n.tag=='{'+W+'}commentRangeEnd' and n.get('{'+W+'}id')==id:active=False",
 "    elif active:text+=''.join(n.xpath('.//w:t/text()',namespaces=ns))",
 "   assert text=='chor t',repr(text);selected[id]=text",
 " print(json.dumps({'changedParts':changed,'selected':selected,'ids':ids,'allXmlValid':True}))",
].join('\n')
function engine(payload){const r=spawnSync(resolve(repo,'.venv/bin/python'),['-c',python],{cwd:repo,env:{...process.env,PYTHONPATH:repo,AGENT_REPORTING_DOC_ENGINE_DIR:runtime},input:JSON.stringify(payload),encoding:'utf8',maxBuffer:20*1024*1024,timeout:120000});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout)}
const revisions={1:engine({mode:'create',path:resolve(output,'revision-1.docx')})},sourceSha256=revisions[1].model.sourceSha256
const requests=[],pageErrors=[],consoleErrors=[],failedResponses=[],chunks=new Map(),identities=[]
let payload,browser,page
const base='http://127.0.0.1:'+port,pathBase='/reports/v1/native/fixture-comment-create/'
const server=createServer(async(req,res)=>{try{const path=new URL(req.url,base).pathname,file=resolve(staticRoot,path.replace(/^\/reports\/v1\/editor\/assets\//,''));assert.ok(file.startsWith(staticRoot+'/'));const bytes=await readFile(file);res.writeHead(200,{'Content-Type':extname(file)==='.js'?'application/javascript':extname(file)==='.css'?'text/css':extname(file)==='.woff2'?'font/woff2':'text/html'});res.end(bytes)}catch{res.writeHead(404);res.end('not found')}})
await new Promise((done,reject)=>{server.once('error',reject);server.listen(port,'127.0.0.1',done)})
try{
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})});page=await browser.newPage({viewport:{width:1600,height:1100}})
 page.on('pageerror',e=>pageErrors.push(e.message));page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text())})
 page.on('response',r=>{const path=new URL(r.url()).pathname;if(r.status()>=400)failedResponses.push({path,status:r.status()});if(r.ok()&&path.endsWith('.js'))identities.push(r.body().then(async bytes=>{const disk=await readFile(resolve(staticRoot,path.replace(/^\/reports\/v1\/editor\/assets\//,'')));assert.equal(sha(bytes),sha(disk),path);chunks.set(path,{path,size:bytes.length,sha256:sha(bytes)})}))})
 await page.route('**/favicon.ico',route=>route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg"/>'}))
 const mediaType='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
 await page.route('**/reports/v1/native/fixture-comment-create/*/api/**',async route=>{
  const request=route.request(),path=new URL(request.url()).pathname,revision=Number(path.split('/')[5]),entry=revisions[revision],post=request.method()==='POST'?request.postDataJSON():undefined;requests.push({path,method:request.method(),payload:post})
  if(path.endsWith('/context'))return route.fulfill({json:{context:{documentId:'fixture-comment-create',format:'docx',revision,parentRevision:revision>1?revision-1:null,scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},sourceFile:{path:'revision-'+revision+'.docx',size:Buffer.from(entry.bytes,'base64').length,sha256:entry.model.sourceSha256,mediaType},origin:'upload'},csrfToken:'fixture-only-csrf',capabilities:{docx_editor:true},editingEnabled:true}})
  if(path.endsWith('/file'))return route.fulfill({body:Buffer.from(entry.bytes,'base64'),contentType:mediaType})
  assert.equal(post?.expectedSha256,entry.model.sourceSha256)
  if(path.endsWith('/preview')){assert.deepEqual(post.operations,[]);return route.fulfill({json:{sourceSha256:entry.model.sourceSha256,draftSha256:entry.model.sourceSha256,model:entry.model}})}
  if(path.endsWith('/save')){
   assert.equal(payload,undefined,'do not repeat a successful save');assert.equal(post.operations.length,2);assert.deepEqual(post.operations.map(o=>o.text),['历史恢复的新批注😀','保存前未失焦的新批注😀'])
   for(const op of post.operations){assert.equal(op.kind,'createComment');assert.deepEqual(op.ranges.map(r=>({from:r.from,to:r.to,text:r.text})),[{from:2,to:8,text:'chor t'}])}
   revisions[2]=engine({mode:'patch',source:resolve(output,'revision-1.docx'),output:resolve(output,'revision-2.docx'),operations:post.operations});payload=post;await writeFile(resolve(output,'saved-request.json'),JSON.stringify(post,null,2))
   return route.fulfill({json:{documentId:'fixture-comment-create',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{word:{downloadUrl:'/new-comment-download.docx',size:Buffer.from(revisions[2].bytes,'base64').length,sha256:revisions[2].model.sourceSha256}},editor:{openUrl:pathBase+'2'},validation:{ok:false,issues:[{code:'fixture_review_pending',message:'新批注版式验收待复核'}]}}})
  }
  throw new Error('unexpected new comment API '+path)
 })
 await page.route('**/new-comment-download.docx',route=>route.fulfill({body:Buffer.from(revisions[2].bytes,'base64'),contentType:mediaType}))
 await page.route(/\/reports\/v1\/native\/fixture-comment-create\/\d+$/,async route=>route.fulfill({body:await readFile(resolve(staticRoot,'native.html')),contentType:'text/html'}))
 const open=async revision=>{await page.goto(base+pathBase+revision);await page.locator('.docx-source-home').waitFor({timeout:60000})}
 const draft=()=>page.evaluate(()=>{const k=Object.keys(localStorage).find(k=>k.startsWith('native-editor-draft:v1:'));return k?JSON.parse(localStorage.getItem(k)).operations:[]})
 const selection=()=>page.locator('.tiptap').evaluate(el=>{el.editor.commands.setTextSelection({from:3,to:9})})
 const newComment=async tab=>{await selection();await page.locator('[data-tab-id="'+tab+'"]').click();const button=page.locator(tab==='review'?'[data-action=comment-create]':'[data-action=insert-new-comment]');assert.equal(await button.locator('svg').count(),1);assert.ok(await button.locator('svg path').count()>0);await button.click();assert.equal(await page.locator('[data-new-comment-selection]').textContent(),'chor t');return page.getByRole('textbox',{name:'新批注文字',exact:true})}
 await open(1)
 if(entryOnly){
  const bodyBefore=await page.locator('.tiptap').innerHTML(),entries=[]
  const expectedPaths=['M 2.99 3.91 h 10.01 v 6.83 h -5.46 L 4.81 13.46 v -2.73 h -1.82 z','M 5.27 6.18 h 5.46 M 5.27 8.46 h 3.64']
  for(const tab of ['review','insert']){
   await page.locator('[data-tab-id="'+tab+'"]').click()
   const button=page.locator(tab==='review'?'[data-action=comment-create]':'[data-action=insert-new-comment]')
   assert.equal(await button.isVisible(),true);assert.equal(await button.isEnabled(),true)
   assert.equal((await button.textContent()).trim(),tab==='review'?'新建批注':'批注')
   assert.equal(await button.getAttribute('aria-label'),tab==='review'?'新建批注':'为所选内容新建批注')
   assert.equal(await button.locator('svg').count(),1)
   const paths=await button.locator('svg path').evaluateAll(nodes=>nodes.map(node=>node.getAttribute('d')))
   assert.deepEqual(paths,expectedPaths)
   entries.push({tab,text:(await button.textContent()).trim(),ariaLabel:await button.getAttribute('aria-label'),enabled:true,sourceSvgPaths:paths})
   await page.screenshot({path:resolve(output,'entry-'+tab+'.png'),fullPage:true})
  }
  assert.equal(await page.locator('.tiptap').innerHTML(),bodyBefore);assert.deepEqual(await draft(),[])
  assert.equal(await page.getByRole('textbox',{name:'新批注文字',exact:true}).count(),0)
  assert.equal(payload,undefined);assert.equal(revisions[2],undefined)
  assert.ok(requests.every(request=>request.method==='GET'||request.path.endsWith('/preview')))
  assert.equal(sha(await readFile(resolve(output,'revision-1.docx'))),sourceSha256)
  await page.waitForLoadState('networkidle');await Promise.all(identities)
  assert.deepEqual(pageErrors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(failedResponses,[])
  for(const entry of ['lazy-unified-main-','lazy-native-main-','lazy-docx-main-'])assert.ok([...chunks.keys()].some(path=>path.includes(entry)),entry)
  const evidence={ok:true,mode:'built-browser-comment-create-entry-only',apiRoutesAreFixtures:true,realPythonNodeBridgeInspect:true,browserVersion:browser.version(),port,manifestSha256,nodeBridgeSha256,sourceSha256,entries,zeroEdits:true,saveRequests:0,exportRequests:0,sourceUnchanged:true,requests,runtimeJavaScript:[...chunks.values()],pageErrors,consoleErrors,failedResponses}
  await writeFile(resolve(output,'evidence.json'),JSON.stringify(evidence,null,2))
  console.log(JSON.stringify({ok:true,mode:evidence.mode,output,manifestSha256,nodeBridgeSha256,javascriptCount:chunks.size,entries,zeroEdits:true,saveRequests:0,exportRequests:0}))
 }else{
 let input=await newComment('review');await input.fill('取消的输入');await page.locator('[data-new-comment-cancel]').click();assert.deepEqual(await draft(),[])
 input=await newComment('insert');await input.fill('历史恢复的新批注😀');await page.locator('[data-new-comment-submit]').click();assert.equal((await draft()).length,1)
 await page.locator('.tiptap').evaluate(el=>el.editor.commands.undo());assert.deepEqual(await draft(),[]);await page.locator('.tiptap').evaluate(el=>el.editor.commands.redo());assert.equal((await draft()).length,1)
 await page.screenshot({path:resolve(output,'new-comment-history.png'),fullPage:true})
 await page.reload();await page.locator('.docx-source-home').waitFor({timeout:60000});assert.equal((await draft())[0].text,'历史恢复的新批注😀')
 input=await newComment('review');await input.fill('保存前未失焦的新批注😀');assert.equal(await input.evaluate(el=>document.activeElement===el),true)
 await page.screenshot({path:resolve(output,'new-comment-unblurred.png'),fullPage:true})
 await page.locator('[data-action=save]').dispatchEvent('click');await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent.includes('已保存修订 2'),null,{timeout:60000})
 assert.equal(await input.isDisabled(),true);assert.equal(await page.getByText('新批注版式验收待复核',{exact:true}).count(),1);assert.equal(await page.getByRole('link',{name:'下载 Word',exact:true}).count(),1)
 const downloaded=Buffer.from(await page.evaluate(async()=>Array.from(new Uint8Array(await(await fetch('/new-comment-download.docx')).arrayBuffer()))));assert.equal(sha(downloaded),revisions[2].model.sourceSha256)
 await writeFile(resolve(output,'downloaded.docx'),downloaded)
 const verified=engine({mode:'verify',source:resolve(output,'revision-1.docx'),bytes:downloaded.toString('base64'),expected:['历史恢复的新批注😀','保存前未失焦的新批注😀']})
 await page.screenshot({path:resolve(output,'new-comment-delivery.png'),fullPage:true});await open(2)
 await page.locator('[data-tab-id=review]').click();await page.locator('[data-action=comment-text-list]').click()
 const finalTarget=revisions[2].model.comments.commentTargets.find(t=>t.text==='保存前未失焦的新批注😀');assert.ok(finalTarget);await page.locator('[data-comment-target]').selectOption(finalTarget.targetId);assert.equal(await page.locator('[data-comment-text]').inputValue(),'保存前未失焦的新批注😀')
 await page.screenshot({path:resolve(output,'new-comment-revision-2.png'),fullPage:true})
 assert.equal(engine({mode:'stale',source:resolve(output,'revision-2.docx'),operations:payload.operations}).rejected,true);assert.equal(sha(await readFile(resolve(output,'revision-1.docx'))),sourceSha256)
 await page.waitForLoadState('networkidle');await Promise.all(identities);assert.deepEqual(pageErrors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(failedResponses,[])
 const evidence={ok:true,mode:'built-browser-comment-create',apiRoutesAreFixtures:true,realPythonNodeBridge:true,browserVersion:browser.version(),port,manifestSha256,nodeBridgeSha256,sourceSha256,outputSha256:revisions[2].model.sourceSha256,verified,payload,requests,runtimeJavaScript:[...chunks.values()],pageErrors,consoleErrors,failedResponses}
 await writeFile(resolve(output,'evidence.json'),JSON.stringify(evidence,null,2));console.log(JSON.stringify({ok:true,output,manifestSha256,nodeBridgeSha256,javascriptCount:chunks.size,verified}))
 }
}catch(error){await page?.screenshot({path:resolve(output,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(resolve(output,'failure.json'),JSON.stringify({error:error.message,stack:error.stack,saved:!!payload,pageErrors,consoleErrors,failedResponses},null,2));throw error}
finally{await browser?.close();await new Promise(done=>server.close(done))}
