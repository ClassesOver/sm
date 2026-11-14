// API route 为显式 fixture；保存实际调用生产 Python/Node bridge，鉴权另有真实 HTTP 专项。
import assert from 'node:assert/strict'
import {inspectReplyComposer} from './office-docx-comment-reply-layout.mjs'
import {createHash} from 'node:crypto'
import {readFile,writeFile,mkdir} from 'node:fs/promises'
import {createServer} from 'node:http'
import {spawnSync} from 'node:child_process'
import {dirname,resolve,extname} from 'node:path'
import {fileURLToPath} from 'node:url'
import {chromium} from 'playwright'
const frontend=resolve(dirname(fileURLToPath(import.meta.url)),'..'),repo=resolve(frontend,'../../..'),staticRoot=resolve(frontend,'../static')
const layoutEnabled=process.env.DOCX_COMMENT_REPLY_LAYOUT==='1',layout={cases:[],failures:[]}
const statusOnly=process.env.DOCX_COMMENT_REPLY_STATUS_ONLY==='1',switchOnly=process.env.DOCX_COMMENT_REPLY_SWITCH_ONLY==='1'
assert.ok(!(statusOnly&&switchOnly),'choose one narrow mode')
const output=process.env.DOCX_COMMENT_REPLY_EVIDENCE??'/tmp/word-comment-reply-browser-20261111',port=Number(process.env.DOCX_COMMENT_REPLY_PORT??4310)
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
 'from smart_reporting.reporting.tests.test_docx_comment_reply import modern_source,rewrite,selected,NS,W,W14,W15',
 'p=json.load(sys.stdin)',
 "if p['mode']=='create':",
 " data=modern_source()",
 " if p.get('longParent'):",
 "  with ZipFile(BytesIO(data)) as z:changes={'word/comments.xml':z.read('word/comments.xml').replace(b'Original note',b'Original note '+b'Long parent comment '*100)}",
 "  data=rewrite(data,changes)",
 " if p.get('twoRoots'):",
 "  with ZipFile(BytesIO(data)) as z:changes={'word/comments.xml':z.read('word/comments.xml').replace(b'Existing reply',b'Second root comment'),'word/commentsExtended.xml':z.read('word/commentsExtended.xml').replace(b' w15:paraIdParent=\"AA000001\"',b'')}",
 "  data=rewrite(data,changes)",
 " Path(p['path']).write_bytes(data);print(json.dumps({'bytes':base64.b64encode(data).decode(),'model':inspect_docx(data)}))",
 "elif p['mode']=='patch':",
 " data=patch_docx(Path(p['source']).read_bytes(),p['operations']);Path(p['output']).write_bytes(data);print(json.dumps({'bytes':base64.b64encode(data).decode(),'model':inspect_docx(data)}))",
 "elif p['mode']=='stale':",
 " try:patch_docx(Path(p['source']).read_bytes(),p['operations'])",
 " except ValueError as e:print(json.dumps({'rejected':True,'reason':str(e)}))",
 " else:raise AssertionError('stale reply accepted')",
 'else:',
 " data=base64.b64decode(p['bytes'])",
 " with ZipFile(p['source']) as a,ZipFile(BytesIO(data)) as b:",
 "  assert b.testzip() is None;assert a.namelist()==b.namelist();changed=[n for n in a.namelist() if a.read(n)!=b.read(n)];assert set(changed)=={'word/document.xml','word/comments.xml','word/commentsExtended.xml'},changed",
 '  for n in b.namelist():',
 "   if n.endswith(('.xml','.rels')):E.fromstring(b.read(n))",
 "  old=E.fromstring(a.read('word/comments.xml'));comments=E.fromstring(b.read('word/comments.xml'));assert len(comments)==4",
 '  for before,after in zip(old,comments):assert E.tostring(before)==E.tostring(after)',
 "  assert [''.join(c.xpath('.//w:t/text()',namespaces=NS)) for c in list(comments)[2:]]==p['expected']",
 "  assert b.read('word/people.xml')==a.read('word/people.xml');assert b.read('custom/preserved.xml')==a.read('custom/preserved.xml')",
 "  oldex=a.read('word/commentsExtended.xml').decode();assert b.read('word/commentsExtended.xml').decode().startswith(oldex.removesuffix('</w15:commentsEx>'))",
 "  doc=E.fromstring(b.read('word/document.xml'));ex=E.fromstring(b.read('word/commentsExtended.xml'));ids=[c.get('{'+W+'}id') for c in comments];assert len(ids)==len(set(ids));parents={}",
 '  for c in list(comments)[2:]:',
 "   pid=c[-1].get('{'+W14+'}paraId');parent=ex.xpath('w15:commentEx[@w15:paraId=$pid]/@w15:paraIdParent',namespaces=NS,pid=pid);assert parent==['AA000001'];cid=c.get('{'+W+'}id');assert selected(doc,cid)==selected(doc,'1')=='Anchor text';parents[cid]='1'",
 " print(json.dumps({'changedParts':changed,'sharedAnchor':'Anchor text','newParents':parents,'ids':ids,'allXmlValid':True,'modernPartsPreserved':True}))",
].join(String.fromCharCode(10))
function engine(payload){const r=spawnSync(resolve(repo,'.venv/bin/python'),['-c',python],{cwd:repo,env:{...process.env,PYTHONPATH:repo,AGENT_REPORTING_DOC_ENGINE_DIR:runtime},input:JSON.stringify(payload),encoding:'utf8',maxBuffer:20*1024*1024,timeout:120000});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout)}
const revisions={1:engine({mode:'create',path:resolve(output,'revision-1.docx'),twoRoots:switchOnly,longParent:process.env.DOCX_COMMENT_REPLY_LONG_PARENT==='1'})},sourceSha256=revisions[1].model.sourceSha256,parentTarget=revisions[1].model.commentReplies.targets.find(t=>t.originalCommentId==='1')
assert.ok(parentTarget?.canReply)
const requests=[],pageErrors=[],consoleErrors=[],failedResponses=[],chunks=new Map(),identities=[]
let payload,browser,page
const base='http://127.0.0.1:'+port,pathBase='/reports/v1/native/fixture-comment-reply/'
const server=createServer(async(req,res)=>{try{const path=new URL(req.url,base).pathname,file=resolve(staticRoot,path.replace(/^\/reports\/v1\/editor\/assets\//,''));assert.ok(file.startsWith(staticRoot+'/'));const bytes=await readFile(file);res.writeHead(200,{'Content-Type':extname(file)==='.js'?'application/javascript':extname(file)==='.css'?'text/css':extname(file)==='.woff2'?'font/woff2':'text/html'});res.end(bytes)}catch{res.writeHead(404);res.end('not found')}})
await new Promise((done,reject)=>{server.once('error',reject);server.listen(port,'127.0.0.1',done)})
try{
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})});page=await browser.newPage({viewport:{width:1600,height:1100}})
 page.on('crash',()=>pageErrors.push('Chromium renderer crashed'));page.on('pageerror',e=>pageErrors.push(e.message));page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text())})
 page.on('response',r=>{const path=new URL(r.url()).pathname;if(r.status()>=400)failedResponses.push({path,status:r.status()});if(r.ok()&&/\.(js|css)$/.test(path))identities.push(r.body().then(async bytes=>{const disk=await readFile(resolve(staticRoot,path.replace(/^\/reports\/v1\/editor\/assets\//,'')));assert.equal(sha(bytes),sha(disk),path);chunks.set(path,{path,size:bytes.length,sha256:sha(bytes)})}).catch(error=>failedResponses.push({path,error:String(error)})))})
 await page.route('**/favicon.ico',route=>route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg"/>'}))
 const mediaType='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
 await page.route('**/reports/v1/native/fixture-comment-reply/*/api/**',async route=>{
  const request=route.request(),path=new URL(request.url()).pathname,revision=Number(path.split('/')[5]),entry=revisions[revision],post=request.method()==='POST'?request.postDataJSON():undefined;requests.push({path,method:request.method(),payload:post})
  if(path.endsWith('/context'))return route.fulfill({json:{context:{documentId:'fixture-comment-reply',format:'docx',revision,parentRevision:revision>1?revision-1:null,scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},sourceFile:{path:'revision-'+revision+'.docx',size:Buffer.from(entry.bytes,'base64').length,sha256:entry.model.sourceSha256,mediaType},origin:'upload'},csrfToken:'fixture-only-csrf',capabilities:{docx_editor:true},editingEnabled:true}})
  if(path.endsWith('/file'))return route.fulfill({body:Buffer.from(entry.bytes,'base64'),contentType:mediaType})
  assert.equal(post?.expectedSha256,entry.model.sourceSha256)
  if(path.endsWith('/preview')){assert.deepEqual(post.operations,[]);return route.fulfill({json:{sourceSha256:entry.model.sourceSha256,draftSha256:entry.model.sourceSha256,model:entry.model}})}
  if(path.endsWith('/save')){
   assert.equal(payload,undefined,'do not repeat a successful save');assert.equal(post.operations.length,2);assert.deepEqual(post.operations.map(o=>o.text),['历史恢复的回复😀','未失焦保存的回复😀'])
   for(const op of post.operations){assert.equal(op.kind,'replyComment');assert.equal(op.targetId,parentTarget.targetId);assert.equal(op.expectedObjectSha256,parentTarget.expectedObjectSha256)}
   revisions[2]=engine({mode:'patch',source:resolve(output,'revision-1.docx'),output:resolve(output,'revision-2.docx'),operations:post.operations});payload=post;await writeFile(resolve(output,'saved-request.json'),JSON.stringify(post,null,2))
   return route.fulfill({json:{documentId:'fixture-comment-reply',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{word:{downloadUrl:'/comment-reply-download.docx',size:Buffer.from(revisions[2].bytes,'base64').length,sha256:revisions[2].model.sourceSha256}},editor:{openUrl:pathBase+'2'},validation:{ok:false,issues:[{code:'fixture_review_pending',message:'批注回复版式验收待复核'}]}}})
  }
  throw new Error('unexpected reply API '+path)
 })
 await page.route('**/comment-reply-download.docx',route=>route.fulfill({body:Buffer.from(revisions[2].bytes,'base64'),contentType:mediaType}))
 await page.route(/\/reports\/v1\/native\/fixture-comment-reply\/\d+$/,async route=>route.fulfill({body:await readFile(resolve(staticRoot,'native.html')),contentType:'text/html'}))
 const open=async revision=>{await page.goto(base+pathBase+revision);await page.locator('.docx-source-home').waitFor({timeout:60000})}
 const draft=()=>page.evaluate(()=>{const k=Object.keys(localStorage).find(k=>k.startsWith('native-editor-draft:v1:'));return k?JSON.parse(localStorage.getItem(k)).operations:[]})
 const openExisting=async()=>{await page.locator('[data-tab-id=review]').click();await page.locator('[data-action=comment-text-list]').click()}
 const reply=async()=>{await openExisting();const button=page.locator('[data-comment-reply]');assert.equal(await button.textContent(),'回复此批注');assert.equal(await button.isEnabled(),true);await button.click();assert.ok((await page.locator('[data-comment-reply-parent]').textContent()).includes('Original note'));return page.getByRole('textbox',{name:'批注回复文字',exact:true})}
 await open(1)
 if(switchOnly){
  const targets=revisions[1].model.commentReplies.targets
  assert.equal(targets.length,2);assert.ok(targets.every(t=>t.canReply&&t.parentId===null))
  const second=targets.find(t=>t.originalCommentId==='2'),input=page.getByRole('textbox',{name:'批注回复文字',exact:true}),header=page.locator('[data-comment-reply-parent]'),status=page.locator('.docx-comment-reply [role=status]')
  const openReply=async target=>{await page.locator('[data-comment-target]').selectOption(target.targetId);assert.equal(await page.locator('[data-comment-reply]').isEnabled(),true);await page.locator('[data-comment-reply]').click()}
  await openExisting();await openReply(parentTarget);assert.equal(await input.inputValue(),'')
  await openReply(second);assert.equal(await header.textContent(),second.author+'：'+second.text)
  await input.fill('只回复第二根线程😀');await page.locator('[data-comment-reply-submit]').click()
  const operations=await draft();assert.equal(operations.length,1);assert.equal(operations[0].targetId,second.targetId);assert.equal(operations[0].text,'只回复第二根线程😀');assert.ok(!operations.some(op=>op.targetId===parentTarget.targetId))
  assert.deepEqual(await page.locator('.tiptap').evaluate(el=>el.editor.getJSON().attrs.nativeCommentReplyOperations),operations)
  await page.screenshot({path:resolve(output,'reply-switched-second-root.png'),fullPage:true})
  await page.locator('.tiptap').evaluate(el=>el.editor.commands.undo());assert.deepEqual(await draft(),[])
  await page.locator('.tiptap').evaluate(el=>el.editor.commands.redo());assert.deepEqual(await draft(),operations)
  await openReply(parentTarget);await input.fill('保留第一根未提交输入');await openReply(second)
  assert.equal(await header.textContent(),parentTarget.author+'：'+parentTarget.text);assert.equal(await input.inputValue(),'保留第一根未提交输入');assert.equal(await status.textContent(),'请先添加或取消当前回复，输入已保留');assert.deepEqual(await draft(),operations)
  const rejectedSwitch={header:await header.textContent(),input:await input.inputValue(),status:await status.textContent()}
  await page.screenshot({path:resolve(output,'reply-nonempty-switch-preserved.png'),fullPage:true})
  await page.locator('[data-comment-reply-cancel]').click();assert.deepEqual(await draft(),operations)
  assert.equal(payload,undefined);assert.equal(revisions[2],undefined);assert.ok(requests.every(request=>request.method==='GET'||request.path.endsWith('/preview')))
  assert.equal(sha(await readFile(resolve(output,'revision-1.docx'))),sourceSha256)
  await page.waitForLoadState('networkidle');await Promise.all(identities);assert.deepEqual(pageErrors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(failedResponses,[])
  for(const entry of ['lazy-unified-main-','lazy-native-main-','lazy-docx-main-'])assert.ok([...chunks.keys()].some(path=>path.includes(entry)),entry)
  const evidence={ok:true,mode:'built-browser-comment-reply-switch-only',apiRoutesAreFixtures:true,realPythonNodeBridgeInspect:true,browserVersion:browser.version(),port,manifestSha256,nodeBridgeSha256,sourceSha256,roots:targets.map(t=>({targetId:t.targetId,originalCommentId:t.originalCommentId,parentId:t.parentId,canReply:t.canReply,author:t.author,text:t.text})),operations,firstRootHasNoNewReply:true,undoRedoPreservedTarget:true,rejectedSwitch,saveRequests:0,exportRequests:0,requests,runtimeJavaScript:[...chunks.values()],pageErrors,consoleErrors,failedResponses}
  await writeFile(resolve(output,'evidence.json'),JSON.stringify(evidence,null,2));console.log(JSON.stringify({ok:true,mode:evidence.mode,output,manifestSha256,nodeBridgeSha256,javascriptCount:chunks.size,actualTargetId:operations[0].targetId,saveRequests:0,exportRequests:0}))
 }else if(statusOnly){
  let input=await reply();await input.fill('状态补验已有回复草稿');await page.locator('[data-comment-reply-submit]').click()
  const seeded=await draft();assert.equal(seeded.length,1);assert.equal(seeded[0].kind,'replyComment')
  await page.reload();await page.locator('.docx-source-home').waitFor({timeout:60000});assert.deepEqual(await draft(),seeded)
  input=await reply();const status=page.locator('.docx-comment-reply [role=status]')
  assert.equal(await input.isEnabled(),true);assert.equal(await status.textContent(),'回复将在添加或保存时加入草稿')
  await page.screenshot({path:resolve(output,'reply-status-recovered.png'),fullPage:true})
  const before=await page.locator('.tiptap').evaluate(el=>el.editor.getJSON())
  await page.locator('.tiptap').evaluate(el=>{el.editor.setEditable(false);el.editor.view.dispatch(el.editor.state.tr.setMeta('reply-status-probe',true))})
  assert.equal(await input.isDisabled(),true);assert.equal(await status.textContent(),'当前文档不可编辑或正在保存')
  await page.locator('.tiptap').evaluate(el=>{el.editor.setEditable(true);el.editor.view.dispatch(el.editor.state.tr.setMeta('reply-status-probe',true))})
  assert.equal(await input.isEnabled(),true);assert.equal(await status.textContent(),'回复将在添加或保存时加入草稿')
  assert.deepEqual(await page.locator('.tiptap').evaluate(el=>el.editor.getJSON()),before);assert.deepEqual(await draft(),seeded)
  await page.screenshot({path:resolve(output,'reply-status-unlocked.png'),fullPage:true})
  assert.equal(payload,undefined);assert.equal(revisions[2],undefined);assert.ok(requests.every(request=>request.method==='GET'||request.path.endsWith('/preview')))
  assert.equal(sha(await readFile(resolve(output,'revision-1.docx'))),sourceSha256)
  await page.waitForLoadState('networkidle');await Promise.all(identities);assert.deepEqual(pageErrors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(failedResponses,[])
  for(const entry of ['lazy-unified-main-','lazy-native-main-','lazy-docx-main-'])assert.ok([...chunks.keys()].some(path=>path.includes(entry)),entry)
  const evidence={ok:true,mode:'built-browser-comment-reply-status-only',apiRoutesAreFixtures:true,realPythonNodeBridgeInspect:true,browserVersion:browser.version(),port,manifestSha256,nodeBridgeSha256,sourceSha256,draftSeededLocally:true,recoveredOperations:seeded,statusAfterUnlock:await status.textContent(),inputEnabled:true,documentUnchangedByLock:true,saveRequests:0,exportRequests:0,requests,runtimeJavaScript:[...chunks.values()],pageErrors,consoleErrors,failedResponses}
  await writeFile(resolve(output,'evidence.json'),JSON.stringify(evidence,null,2));console.log(JSON.stringify({ok:true,mode:evidence.mode,output,manifestSha256,nodeBridgeSha256,javascriptCount:chunks.size,statusAfterUnlock:evidence.statusAfterUnlock,saveRequests:0,exportRequests:0}))
 }else{
 let input=await reply();
 if(layoutEnabled){
  await input.fill('长回复内容😀\n'.repeat(100));await inspectReplyComposer(page,{output,phase:'editing-long',evidence:layout,draft})
  if(process.env.DOCX_COMMENT_REPLY_BASELINE)throw new Error('baseline layout defects: '+layout.failures.join('; '))
  assert.deepEqual(layout.failures,[])
  await page.locator('[data-comment-reply-close]').click();assert.equal(await page.locator('[data-comment-reply]').evaluate(node=>document.activeElement===node),true);assert.deepEqual(await draft(),[])
  input=await reply()
 }
 await input.fill('取消的回复');await page.locator('[data-comment-reply-cancel]').click();assert.deepEqual(await draft(),[])
 input=await reply();await input.fill('历史恢复的回复😀');await page.locator('[data-comment-reply-submit]').click();assert.equal((await draft()).length,1)
 if(layoutEnabled){await inspectReplyComposer(page,{output,phase:'draft',evidence:layout,draft});assert.deepEqual(layout.failures,[])}
 await page.locator('.tiptap').evaluate(el=>el.editor.commands.undo());assert.deepEqual(await draft(),[]);await page.locator('.tiptap').evaluate(el=>el.editor.commands.redo());assert.equal((await draft()).length,1)
 await page.screenshot({path:resolve(output,'reply-history.png'),fullPage:true});await page.reload();await page.locator('.docx-source-home').waitFor({timeout:60000});assert.equal((await draft())[0].text,'历史恢复的回复😀')
 input=await reply();await input.fill('未失焦保存的回复😀');assert.equal(await input.evaluate(el=>document.activeElement===el),true);await page.screenshot({path:resolve(output,'reply-unblurred.png'),fullPage:true})
 await page.locator('[data-action=save]').dispatchEvent('click');await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent.includes('已保存修订 2'),null,{timeout:60000})
 assert.equal(await input.isDisabled(),true);assert.equal(await page.getByText('批注回复版式验收待复核',{exact:true}).count(),1);assert.equal(await page.getByRole('link',{name:'下载 Word',exact:true}).count(),1)
 if(layoutEnabled){await inspectReplyComposer(page,{output,phase:'saved',evidence:layout,draft});assert.deepEqual(layout.failures,[])}
 const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('link',{name:'下载 Word',exact:true}).click()]);await download.saveAs(resolve(output,'downloaded.docx'))
 const downloaded=await readFile(resolve(output,'downloaded.docx'));assert.equal(sha(downloaded),revisions[2].model.sourceSha256);await writeFile(resolve(output,'downloaded.docx'),downloaded)
 const verified=engine({mode:'verify',source:resolve(output,'revision-1.docx'),bytes:downloaded.toString('base64'),expected:['历史恢复的回复😀','未失焦保存的回复😀']});await page.screenshot({path:resolve(output,'reply-delivery.png'),fullPage:true})
 await open(2);await openExisting();const finalTarget=revisions[2].model.commentReplies.targets.find(t=>t.text==='未失焦保存的回复😀');assert.equal(finalTarget?.parentId,'1');await page.locator('[data-comment-target]').selectOption(finalTarget.targetId)
 assert.equal(await page.locator('[data-comment-text]').inputValue(),'未失焦保存的回复😀');assert.equal(await page.locator('[data-comment-thread]').textContent(),'回复根批注 #1');assert.equal(await page.locator('[data-comment-reply]').isDisabled(),true);await page.screenshot({path:resolve(output,'reply-revision-2.png'),fullPage:true})
 assert.equal(engine({mode:'stale',source:resolve(output,'revision-2.docx'),operations:payload.operations}).rejected,true);assert.equal(sha(await readFile(resolve(output,'revision-1.docx'))),sourceSha256)
 await page.waitForLoadState('networkidle');await Promise.all(identities);assert.deepEqual(pageErrors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(failedResponses,[])
 assert.equal(sha(await readFile(resolve(staticRoot,'.vite/manifest.json'))),manifestSha256)
 const evidence={ok:true,mode:'built-browser-comment-reply',layout,actualBrowserDownload:true,apiRoutesAreFixtures:true,realPythonNodeBridge:true,browserVersion:browser.version(),port,manifestSha256,nodeBridgeSha256,sourceSha256,outputSha256:revisions[2].model.sourceSha256,verified,payload,requests,runtimeJavaScript:[...chunks.values()],pageErrors,consoleErrors,failedResponses}
 await writeFile(resolve(output,'evidence.json'),JSON.stringify(evidence,null,2));console.log(JSON.stringify({ok:true,output,manifestSha256,nodeBridgeSha256,assetCount:chunks.size,verified}))
 }
}catch(error){if(page&&!page.isClosed())await page.content().then(html=>writeFile(resolve(output,'failure.html'),html)).catch(()=>{});await page?.screenshot({path:resolve(output,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(resolve(output,'failure.json'),JSON.stringify({error:error.message,stack:error.stack,saved:!!payload,requests,pageErrors,consoleErrors,failedResponses},null,2));throw error}
finally{await browser?.close();await new Promise(done=>server.close(done))}
