import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { access, mkdir, readFile, symlink, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { resolve, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const staticRoot=resolve(process.env.DOCX_COMMENT_BATCH_STATIC_ROOT??''),sharedStatic=resolve(frontend,'../static')
assert.ok(process.env.DOCX_COMMENT_BATCH_STATIC_ROOT,'set DOCX_COMMENT_BATCH_STATIC_ROOT to the root-provided frozen build')
assert.notEqual(staticRoot,sharedStatic,'never run this smoke against shared static assets')
const port=Number(process.env.DOCX_COMMENT_BATCH_PORT??4211),base='http://127.0.0.1:'+port
const output=process.env.DOCX_COMMENT_BATCH_SMOKE_DIR??await import('node:fs/promises').then(fs=>fs.mkdtemp(join(tmpdir(),'docx-comment-batch-delete-')))
const runtime=process.env.DOCX_COMMENT_BATCH_ENGINE_DIR??join(output,'engine'),mediaType='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const sha=bytes=>createHash('sha256').update(bytes).digest('hex')
const manifestSha=sha(await readFile(join(staticRoot,'.vite/manifest.json')))
await mkdir(output,{recursive:true})
try{await access(join(runtime,'dist/edit-docx.mjs'))}catch{
 await mkdir(runtime,{recursive:true})
 for(const name of ['bridge','packages','node_modules','package.json'])try{await access(join(runtime,name))}catch{await symlink(join(repo,'smart_reporting/reporting/doc_engine',name),join(runtime,name))}
 const bundled=spawnSync('npm',['run','bundle:bridges'],{cwd:runtime,encoding:'utf8',timeout:120000})
 assert.equal(bundled.status,0,bundled.stderr)
}
const pythonSource=[
 'import base64,json,sys',
 'from io import BytesIO',
 'from pathlib import Path',
 'from zipfile import ZipFile,ZIP_DEFLATED',
 'from lxml import etree as E',
 'from smart_reporting.reporting.delivery.docx_native import inspect_docx,patch_docx',
 'from smart_reporting.reporting.tests.test_docx_comment_reply import modern_source,W,W14,W15,NS',
 'from smart_reporting.reporting.tests.test_docx_comment_text_host import source',
 'p=json.load(sys.stdin)',
 'def rewrite(data,changes):',
 ' out=BytesIO()',
 ' with ZipFile(BytesIO(data)) as a,ZipFile(out,"w",ZIP_DEFLATED) as b:',
 '  for n in a.namelist():b.writestr(n,changes.get(n,a.read(n)))',
 '  for n,v in changes.items():',
 '   if n not in a.namelist():b.writestr(n,v)',
 ' return out.getvalue()',
 'def multi_thread_source():',
 ' data=modern_source()',
 ' with ZipFile(BytesIO(data)) as z:',
 '  comments=E.fromstring(z.read("word/comments.xml"));document=E.fromstring(z.read("word/document.xml"));extended=E.fromstring(z.read("word/commentsExtended.xml"))',
 '  comment=E.SubElement(comments,"{"+W+"}comment",{"{"+W+"}id":"3","{"+W+"}author":"Bob"})',
 '  para=E.SubElement(comment,"{"+W+"}p",{"{"+W14+"}paraId":"AA000003"});run=E.SubElement(para,"{"+W+"}r");E.SubElement(run,"{"+W+"}t").text="Open note"',
 '  bodyPara=document.find(".//w:body/w:p",NS);start=E.Element("{"+W+"}commentRangeStart",{"{"+W+"}id":"3"});end=E.Element("{"+W+"}commentRangeEnd",{"{"+W+"}id":"3"});refRun=E.Element("{"+W+"}r");E.SubElement(refRun,"{"+W+"}commentReference",{"{"+W+"}id":"3"})',
 '  bodyPara.insert(1 if bodyPara.find("w:pPr",NS) is not None else 0,start);bodyPara.append(end);bodyPara.append(refRun)',
 '  E.SubElement(extended,"{"+W15+"}commentEx",{"{"+W15+"}paraId":"AA000003","{"+W15+"}done":"0"})',
 '  changes={"word/comments.xml":E.tostring(comments,encoding="utf-8",xml_declaration=True),"word/document.xml":E.tostring(document,encoding="utf-8",xml_declaration=True),"word/commentsExtended.xml":E.tostring(extended,encoding="utf-8",xml_declaration=True)}',
 '  for n in ("word/_rels/document.xml.rels","[Content_Types].xml"):changes[n]=z.read(n)',
 ' return rewrite(data,changes)',
 'if p["mode"]=="create":',
 ' data=multi_thread_source();Path(p["path"]).write_bytes(data);print(json.dumps({"bytes":base64.b64encode(data).decode(),"model":inspect_docx(data)}))',
 'elif p["mode"]=="patch":',
 ' data=Path(p["source"]).read_bytes();out=patch_docx(data,p["operations"]);Path(p["output"]).write_bytes(out);print(json.dumps({"bytes":base64.b64encode(out).decode(),"model":inspect_docx(out)}))',
 'elif p["mode"]=="verify":',
 ' before=Path(p["source"]).read_bytes();saved=base64.b64decode(p["bytes"])',
 ' with ZipFile(BytesIO(before)) as a,ZipFile(BytesIO(saved)) as b:',
 '  assert b.testzip() is None and a.namelist()==b.namelist()',
 '  for n in b.namelist():',
 '   if n.endswith((".xml",".rels")):E.fromstring(b.read(n))',
 '  x=E.fromstring(a.read("word/document.xml"));y=E.fromstring(b.read("word/document.xml"))',
 '  assert x.xpath(".//w:body//w:t/text()",namespaces=NS)==y.xpath(".//w:body//w:t/text()",namespaces=NS)',
 '  for name in ("commentRangeStart","commentRangeEnd","commentReference"):assert not y.findall(".//w:"+name,NS)',
 '  assert not E.fromstring(b.read("word/comments.xml")).findall("w:comment",NS)',
 '  assert not inspect_docx(saved)["commentThreads"]["targets"]',
 '  reply_ids=[target["originalCommentId"] for target in inspect_docx(before)["commentThreads"]["targets"] if target["parentId"] is not None]',
 '  assert reply_ids and all(x.xpath(".//w:commentRangeStart[@w:id=$id]",namespaces=NS,id=comment_id) and x.xpath(".//w:commentRangeEnd[@w:id=$id]",namespaces=NS,id=comment_id) and x.xpath(".//w:commentReference[@w:id=$id]",namespaces=NS,id=comment_id) for comment_id in reply_ids)',
 '  assert all(not y.xpath(".//w:commentRangeStart[@w:id=$id] | .//w:commentRangeEnd[@w:id=$id] | .//w:commentReference[@w:id=$id]",namespaces=NS,id=comment_id) for comment_id in reply_ids)',
 '  changed=[n for n in a.namelist() if a.read(n)!=b.read(n)]',
 '  allowed={"word/document.xml","word/comments.xml","word/commentsExtended.xml","word/commentsIds.xml"}',
 '  assert changed and set(changed)<=allowed,(changed,allowed)',
 ' print(json.dumps({"changedParts":changed,"replyIds":reply_ids,"bodyText":y.xpath(".//w:body//w:t/text()",namespaces=NS)}))',
].join('\n')
const python=input=>{
 const result=spawnSync(join(repo,'.venv/bin/python'),['-c',pythonSource],{cwd:repo,input:JSON.stringify(input),encoding:'utf8',maxBuffer:20*1024*1024,timeout:120000,env:{...process.env,PYTHONPATH:repo,AGENT_REPORTING_DOC_ENGINE_DIR:runtime}})
 assert.equal(result.status,0,result.stderr);return JSON.parse(result.stdout.trim())
}
const sourcePath=join(output,'revision-1.docx'),savedPath=join(output,'revision-2.docx'),initial=python({mode:'create',path:sourcePath})
const roots=initial.model.commentThreads.targets.filter(target=>target.parentId===null)
assert.equal(roots.length,2);assert.equal(roots.filter(target=>target.done).length,1)
assert.ok(initial.model.commentThreads.targets.some(target=>target.parentId!==null),'fixture must include a reply thread member')
const opFor=target=>({kind:'deleteComment',sourceId:target.sourceId,targetId:target.targetId,expectedCommentsSha256:target.expectedCommentsSha256,expectedObjectSha256:target.expectedObjectSha256})
const expectedResolved=[opFor(roots.find(target=>target.done))],expectedAll=roots.map(opFor)
const state={revisions:{1:initial},payload:null}
let server,browser
const chunks=new Map(),errors=[]
try{
 server=spawn('./node_modules/.bin/vite',['preview','--host','127.0.0.1','--port',String(port),'--strictPort','--outDir',staticRoot],{cwd:frontend,stdio:'ignore'})
 let serving=false
 for(let n=0;n<120;n++){try{if((await fetch(base+'/reports/v1/editor/assets/native.html')).ok){serving=true;break}}catch{}await delay(250)}
 assert.equal(serving,true,'root-provided isolated preview unavailable')
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})})
 const page=await browser.newPage({viewport:{width:1440,height:900}})
 page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')errors.push(message.text())})
 page.on('response',response=>{const path=new URL(response.url()).pathname,assetBase='/reports/v1/editor/assets/';if(response.ok()&&/\.(?:m?js|css)$/.test(path)&&path.startsWith(assetBase+'assets/'))chunks.set(path,response.body().then(async bytes=>{assert.equal(sha(bytes),sha(await readFile(join(staticRoot,path.slice(assetBase.length)))),path);return sha(bytes)}))})
 const revisionOf=request=>Number(new URL(request.url()).pathname.split('/')[5])
 await page.route('**/reports/v1/native/fixture-comment-batch/*/api/context',route=>{
  const revision=revisionOf(route.request()),entry=state.revisions[revision],bytes=Buffer.from(entry.bytes,'base64')
  return route.fulfill({json:{context:{documentId:'fixture-comment-batch',format:'docx',revision,parentRevision:revision>1?revision-1:null,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'revision-'+revision+'.docx',size:bytes.length,sha256:entry.model.sourceSha256,mediaType},origin:'report'},csrfToken:'fixture-csrf',capabilities:{docx_editor:true},editingEnabled:true}})
 })
 await page.route('**/reports/v1/native/fixture-comment-batch/*/api/file',route=>route.fulfill({body:Buffer.from(state.revisions[revisionOf(route.request())].bytes,'base64'),contentType:mediaType}))
 await page.route('**/reports/v1/native/fixture-comment-batch/*/api/preview',route=>{const model=state.revisions[revisionOf(route.request())].model;return route.fulfill({json:{sourceSha256:model.sourceSha256,draftSha256:model.sourceSha256,model}})})
 await page.route('**/reports/v1/native/fixture-comment-batch/*/api/save',async route=>{
  assert.equal(state.payload,null,'one batch-delete save only');const revision=revisionOf(route.request()),payload=route.request().postDataJSON()
  assert.equal(payload.operations.length,2);assert.deepEqual(payload.operations,expectedAll)
  state.revisions[revision+1]=python({mode:'patch',source:sourcePath,output:savedPath,operations:payload.operations});state.payload=payload
  const bytes=Buffer.from(state.revisions[revision+1].bytes,'base64')
  return route.fulfill({json:{documentId:'fixture-comment-batch',revision:revision+1,parentRevision:revision,revisionRegistered:true,artifacts:{word:{downloadUrl:'/comment-batch-delete.docx',size:bytes.length,sha256:sha(bytes)}},editor:{openUrl:'/reports/v1/native/fixture-comment-batch/'+(revision+1)},validation:{ok:false,issues:[{code:'fixture_review_pending',message:'批注删除专项保留验收告警'}]}}})
 })
 await page.route('**/comment-batch-delete.docx',route=>route.fulfill({body:Buffer.from(state.revisions[2].bytes,'base64'),contentType:mediaType,headers:{'Content-Disposition':'attachment; filename="comments-deleted.docx"'}}))
 await page.route(/\/reports\/v1\/native\/fixture-comment-batch\/\d+$/,async route=>route.fulfill({body:await readFile(join(staticRoot,'native.html')),contentType:'text/html'}))
 const open=async revision=>{await page.goto(base+'/reports/v1/native/fixture-comment-batch/'+revision);await page.locator('.docx-source-home').waitFor({timeout:60000})}
 const draft=()=>page.evaluate(()=>{const key=Object.keys(localStorage).find(value=>value.startsWith('native-editor-draft:v1:'));return key?JSON.parse(localStorage.getItem(key)).operations:[]})
 await open(1);await page.locator('[data-tab-id="review"]').click()
 const resolved=page.locator('[data-action="comment-delete-resolved"]'),all=page.locator('[data-action="comment-delete-all"]')
 assert.equal(await resolved.isEnabled(),true);assert.equal(await all.isEnabled(),true)
 let dialog=page.waitForEvent('dialog'),click=resolved.click(),confirm=await dialog;assert.match(confirm.message(),/所有已解决的批注/);await confirm.accept();await click
 assert.deepEqual(await draft(),expectedResolved)
 assert.equal(await resolved.isDisabled(),true);assert.equal(await all.isEnabled(),true)
 await page.screenshot({path:join(output,'comment-batch-resolved-deleted-draft.png'),fullPage:true})
 assert.equal(await page.locator('.tiptap').evaluate(element=>element.editor.commands.undo()),true)
 assert.deepEqual(await draft(),[])
 assert.equal(await resolved.isEnabled(),true);assert.equal(await all.isEnabled(),true)
 dialog=page.waitForEvent('dialog');click=all.click();confirm=await dialog;assert.match(confirm.message(),/文档中的所有批注/);await confirm.accept();await click
 assert.deepEqual(await draft(),expectedAll)
 assert.equal(await resolved.isDisabled(),true);assert.equal(await all.isDisabled(),true)
 await page.screenshot({path:join(output,'comment-batch-all-deleted-draft.png'),fullPage:true})
 await page.locator('[data-action="save"]').dispatchEvent('click')
 await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent.includes('已保存修订 2'),null,{timeout:60000})
 assert.equal(await page.getByText('批注删除专项保留验收告警',{exact:true}).count(),1)
 await open(2)
 const response=await page.evaluate(async url=>{const response=await fetch(url);return {status:response.status,contentDisposition:response.headers.get('content-disposition'),bytes:Array.from(new Uint8Array(await response.arrayBuffer()))}},'/comment-batch-delete.docx')
 const downloaded=Buffer.from(response.bytes);assert.equal(response.status,200);assert.match(response.contentDisposition??'',/comments-deleted\.docx/)
 assert.equal(sha(downloaded),sha(await readFile(savedPath)));await writeFile(join(output,'downloaded.docx'),downloaded)
 const verified=python({mode:'verify',source:sourcePath,bytes:downloaded.toString('base64')})
 assert.equal(sha(downloaded),state.revisions[2].model.sourceSha256);assert.deepEqual(state.revisions[2].model.commentThreads.targets,[])
 await open(2);await page.locator('[data-tab-id="review"]').click()
 assert.equal(await resolved.isDisabled(),true);assert.equal(await all.isDisabled(),true)
 await page.screenshot({path:join(output,'comment-batch-deleted-reopened.png'),fullPage:true})
 const loadedChunks=Object.fromEntries(await Promise.all([...chunks].map(async([path,promise])=>[path,await promise])))
 assert.deepEqual(errors,[]);assert.equal(sha(await readFile(join(staticRoot,'.vite/manifest.json')),),manifestSha)
 const result={ok:true,apiRoutesAreFixtures:true,realPythonNodeBridge:true,buildManifestSha256:manifestSha,sourceSha256:initial.model.sourceSha256,outputSha256:state.revisions[2].model.sourceSha256,saveRequests:1,resolvedUndoOperations:expectedResolved,allOperations:expectedAll,downloadStatus:response.status,contentDisposition:response.contentDisposition,downloadedSha256:sha(downloaded),savedArtifactSha256:sha(await readFile(savedPath)),changedParts:verified.changedParts,deletedReplyIds:verified.replyIds,bodyText:verified.bodyText,reopenedCommentTargets:state.revisions[2].model.commentThreads.targets.length,loadedChunks,errors}
 await writeFile(join(output,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({ok:true,output,manifestSha,saveRequests:1,changedParts:verified.changedParts,downloadedSha256:result.downloadedSha256,loadedJavascript:chunks.size}))
}catch(error){await writeFile(join(output,'failure.json'),JSON.stringify({message:String(error),stack:error.stack,saved:!!state.payload},null,2));throw error}
finally{await browser?.close();server?.kill()}
